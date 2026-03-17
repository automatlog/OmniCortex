# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: MIT
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.


# Copyright (c) Kyutai, all rights reserved.
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import argparse
import asyncio
from dataclasses import dataclass
import json
import random
import os
from pathlib import Path
import tarfile
import time
import secrets
import sys
from typing import Literal, Optional

import aiohttp
from aiohttp import web
from huggingface_hub import hf_hub_download
import numpy as np
import sentencepiece
import sphn
import torch
import random

from .client_utils import make_log, colorize
from .models import loaders, MimiModel, LMModel, LMGen
from .utils.connection import create_ssl_context, get_lan_ip
from .utils.logging import setup_logger, ColorizedLog


logger = setup_logger(__name__)
DeviceString = Literal["cuda"] | Literal["cpu"] #| Literal["mps"]

def torch_auto_device(requested: Optional[DeviceString] = None) -> torch.device:
    """Return a torch.device based on the requested string or availability."""
    if requested is not None:
        return torch.device(requested)
    if torch.cuda.is_available():
        return torch.device("cuda")
    #elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
    #    return torch.device("mps")
    return torch.device("cpu")


def seed_all(seed):
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)  # for multi-GPU setups
    random.seed(seed)
    np.random.seed(seed)
    torch.backends.cudnn.deterministic = False
    torch.backends.cudnn.benchmark = False


def wrap_with_system_tags(text: str) -> str:
    """Add system tags as the model expects if they are missing.
    Example: "<system> You enjoy having a good conversation. Have a deep conversation about technology. Your name is Jane. <system>"
    """
    cleaned = text.strip()
    if cleaned.startswith("<system>") and cleaned.endswith("<system>"):
        return cleaned
    return f"<system> {cleaned} <system>"


@dataclass
class ServerState:
    mimi: MimiModel
    other_mimi: MimiModel
    text_tokenizer: sentencepiece.SentencePieceProcessor
    lm_gen: LMGen
    lock: asyncio.Lock

    def __init__(self, mimi: MimiModel, other_mimi: MimiModel, text_tokenizer: sentencepiece.SentencePieceProcessor,
                 lm: LMModel, device: str | torch.device, voice_prompt_dir: str | None = None,
                 save_voice_prompt_embeddings: bool = False,
                 omnicortex_base_url: str = "",
                 omnicortex_api_key: str = "",
                 omnicortex_user_id: str = "",
                 omnicortex_context_top_k: int = 3):
        self.mimi = mimi
        self.other_mimi = other_mimi
        self.text_tokenizer = text_tokenizer
        self.device = device
        self.voice_prompt_dir = voice_prompt_dir
        self.omnicortex_base_url = (omnicortex_base_url or "").rstrip("/")
        self.omnicortex_api_key = (omnicortex_api_key or "").strip()
        self.omnicortex_user_id = (omnicortex_user_id or "").strip()
        self.omnicortex_context_top_k = max(1, min(6, int(omnicortex_context_top_k or 3)))
        self.frame_size = int(self.mimi.sample_rate / self.mimi.frame_rate)
        self.lm_gen = LMGen(lm,
                            audio_silence_frame_cnt=int(0.5 * self.mimi.frame_rate),
                            sample_rate=self.mimi.sample_rate,
                            device=device,
                            frame_rate=self.mimi.frame_rate,
                            save_voice_prompt_embeddings=save_voice_prompt_embeddings,
        )
        
        self.lock = asyncio.Lock()
        self.mimi.streaming_forever(1)
        self.other_mimi.streaming_forever(1)
        self.lm_gen.streaming_forever(1)

    def _omnicortex_headers(
        self,
        api_key_override: str = "",
        user_id_override: str = "",
    ) -> dict[str, str]:
        headers: dict[str, str] = {}
        api_key = (api_key_override or self.omnicortex_api_key or "").strip()
        user_id = (user_id_override or self.omnicortex_user_id or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        if user_id:
            headers["x-user-id"] = user_id
        return headers

    async def _omnicortex_get_json(
        self,
        path: str,
        params: Optional[dict] = None,
        api_key_override: str = "",
        user_id_override: str = "",
    ):
        if not self.omnicortex_base_url:
            raise RuntimeError("OMNICORTEX_BASE_URL is not configured")
        url = f"{self.omnicortex_base_url}{path}"
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                url,
                params=params or {},
                headers=self._omnicortex_headers(
                    api_key_override=api_key_override,
                    user_id_override=user_id_override,
                ),
            ) as response:
                body = await response.text()
                if response.status >= 400:
                    raise RuntimeError(f"{path} failed ({response.status}): {body[:400]}")
                return json.loads(body) if body else {}

    async def _omnicortex_post_json(
        self,
        path: str,
        payload: Optional[dict] = None,
        api_key_override: str = "",
        user_id_override: str = "",
    ):
        if not self.omnicortex_base_url:
            raise RuntimeError("OMNICORTEX_BASE_URL is not configured")
        url = f"{self.omnicortex_base_url}{path}"
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                url,
                json=payload or {},
                headers=self._omnicortex_headers(
                    api_key_override=api_key_override,
                    user_id_override=user_id_override,
                ),
            ) as response:
                body = await response.text()
                if response.status >= 400:
                    raise RuntimeError(f"{path} failed ({response.status}): {body[:400]}")
                return json.loads(body) if body else {}

    async def fetch_agents(
        self,
        api_key_override: str = "",
        user_id_override: str = "",
    ) -> list[dict]:
        payload = await self._omnicortex_get_json(
            "/agents",
            api_key_override=api_key_override,
            user_id_override=user_id_override,
        )
        if not isinstance(payload, list):
            return []
        agents: list[dict] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            agent_id = str(item.get("id") or "").strip()
            if not agent_id:
                continue
            agents.append(
                {
                    "id": agent_id,
                    "name": str(item.get("agent_name") or item.get("name") or agent_id),
                    "type": str(item.get("agent_type") or item.get("role_type") or ""),
                }
            )
        return agents

    async def fetch_agent_prompt(
        self,
        agent_id: str,
        context_query: str = "",
        api_key_override: str = "",
        user_id_override: str = "",
    ) -> str:
        detail = await self._omnicortex_get_json(
            f"/agents/{agent_id}",
            api_key_override=api_key_override,
            user_id_override=user_id_override,
        )
        base_prompt = str((detail or {}).get("system_prompt") or "").strip()
        if not base_prompt:
            base_prompt = "You are a helpful assistant."

        try:
            ctx_payload = await self._omnicortex_get_json(
                f"/agents/{agent_id}/voice-context",
                params={
                    "query": context_query,
                    "top_k": self.omnicortex_context_top_k,
                },
                api_key_override=api_key_override,
                user_id_override=user_id_override,
            )
            context_text = str((ctx_payload or {}).get("context") or "").strip()
            if context_text:
                base_prompt = (
                    f"{base_prompt}\n\n"
                    "Use the following retrieved context when relevant. "
                    "If context does not answer the user, say you do not know.\n"
                    f"{context_text}"
                )
        except Exception as context_error:
            logger.warning("voice-context lookup failed for agent %s: %s", agent_id, context_error)

        return base_prompt

    async def fetch_agent_detail(
        self,
        agent_id: str,
        api_key_override: str = "",
        user_id_override: str = "",
    ) -> dict:
        detail = await self._omnicortex_get_json(
            f"/agents/{agent_id}",
            api_key_override=api_key_override,
            user_id_override=user_id_override,
        )
        docs = []
        try:
            docs = await self._omnicortex_get_json(
                f"/agents/{agent_id}/documents",
                api_key_override=api_key_override,
                user_id_override=user_id_override,
            )
            if not isinstance(docs, list):
                docs = []
        except Exception:
            docs = []

        return {
            "id": str((detail or {}).get("id") or agent_id),
            "name": str((detail or {}).get("name") or ""),
            "agent_type": str((detail or {}).get("agent_type") or (detail or {}).get("role_type") or ""),
            "description": str((detail or {}).get("description") or ""),
            "urls": (detail or {}).get("urls") or [],
            "image_urls": (detail or {}).get("image_urls") or [],
            "video_urls": (detail or {}).get("video_urls") or [],
            "conversation_starters": (detail or {}).get("conversation_starters") or [],
            "conversation_end": (detail or {}).get("conversation_end") or [],
            "document_count": int((detail or {}).get("document_count") or 0),
            "message_count": int((detail or {}).get("message_count") or 0),
            "documents": docs,
        }

    async def fetch_voice_profile(
        self,
        api_key_override: str = "",
        user_id_override: str = "",
    ) -> dict:
        payload = await self._omnicortex_get_json(
            "/voice/profile",
            api_key_override=api_key_override,
            user_id_override=user_id_override,
        )
        profile = payload.get("profile") if isinstance(payload, dict) else {}
        return profile if isinstance(profile, dict) else {}

    async def save_voice_profile(
        self,
        profile: dict,
        api_key_override: str = "",
        user_id_override: str = "",
    ) -> dict:
        payload = await self._omnicortex_post_json(
            "/voice/profile",
            payload=profile or {},
            api_key_override=api_key_override,
            user_id_override=user_id_override,
        )
        profile_out = payload.get("profile") if isinstance(payload, dict) else {}
        return profile_out if isinstance(profile_out, dict) else {}
    
    def warmup(self):
        for _ in range(4):
            chunk = torch.zeros(1, 1, self.frame_size, dtype=torch.float32, device=self.device)
            codes = self.mimi.encode(chunk)
            _ = self.other_mimi.encode(chunk)
            for c in range(codes.shape[-1]):
                tokens = self.lm_gen.step(codes[:, :, c: c + 1])
                if tokens is None:
                    continue
                _ = self.mimi.decode(tokens[:, 1:9])
                _ = self.other_mimi.decode(tokens[:, 1:9])

        if self.device.type == 'cuda':
            torch.cuda.synchronize()


    async def handle_chat(self, request):
        expected_token = os.environ.get("MOSHI_API_TOKEN", "")
        if expected_token:
            auth_token = request.query.get("token")
            if not auth_token:
                auth_header = request.headers.get("Authorization", "")
                if auth_header.startswith("Bearer "):
                    auth_token = auth_header[len("Bearer "):].strip()
            if auth_token != expected_token:
                return web.Response(status=401, text="Unauthorized")

        # Agent-first mode for PersonaPlex UI: ignore direct text_prompt when agent_id is provided.
        agent_id = request.query.get("agent_id", "").strip()
        context_query = request.query.get("context_query", "").strip()
        if not context_query:
            # Fallback: use incoming text_prompt as retrieval seed if provided.
            context_query = request.query.get("text_prompt", "").strip()[:400]
        omni_bearer = request.query.get("omni_bearer", "").strip()
        omni_user_id = request.query.get("omni_user_id", "").strip()
        text_prompt = request.query.get("text_prompt", "")
        if agent_id:
            try:
                text_prompt = await self.fetch_agent_prompt(
                    agent_id,
                    context_query=context_query,
                    api_key_override=omni_bearer,
                    user_id_override=omni_user_id,
                )
            except Exception as error:
                return web.Response(
                    status=400,
                    text=f"Unable to resolve agent prompt for '{agent_id}': {error}",
                )

        ws = web.WebSocketResponse()
        await ws.prepare(request)
        clog = ColorizedLog.randomize()
        peer = request.remote  # IP
        peer_port = request.transport.get_extra_info("peername")[1]  # Port
        clog.log("info", f"Incoming connection from {peer}:{peer_port}")

        # self.lm_gen.temp = float(request.query["audio_temperature"])
        # self.lm_gen.temp_text = float(request.query["text_temperature"])
        # self.lm_gen.top_k_text = max(1, int(request.query["text_topk"]))
        # self.lm_gen.top_k = max(1, int(request.query["audio_topk"]))
        
        # Construct full voice prompt path
        requested_voice_prompt_path = None
        voice_prompt_path = None
        voice_prompt_filename = request.query.get("voice_prompt", "").strip()
        if self.voice_prompt_dir is not None:
            if voice_prompt_filename:
                requested_voice_prompt_path = os.path.join(self.voice_prompt_dir, voice_prompt_filename)
                # If the voice prompt file does not exist, fail fast.
                if not os.path.exists(requested_voice_prompt_path):
                    raise FileNotFoundError(
                        f"Requested voice prompt '{voice_prompt_filename}' not found in '{self.voice_prompt_dir}'"
                    )
                voice_prompt_path = requested_voice_prompt_path

        seed = None
        if "seed" in request.query:
            try:
                seed = int(request.query["seed"])
            except ValueError as exc:
                raise web.HTTPBadRequest(text="Invalid seed") from exc

        async def recv_loop():
            nonlocal close
            try:
                async for message in ws:
                    if message.type == aiohttp.WSMsgType.ERROR:
                        clog.log("error", f"{ws.exception()}")
                        break
                    elif message.type == aiohttp.WSMsgType.CLOSED:
                        break
                    elif message.type == aiohttp.WSMsgType.CLOSE:
                        break
                    elif message.type != aiohttp.WSMsgType.BINARY:
                        clog.log("error", f"unexpected message type {message.type}")
                        continue
                    message = message.data
                    if not isinstance(message, bytes):
                        clog.log("error", f"unsupported message type {type(message)}")
                        continue
                    if len(message) == 0:
                        clog.log("warning", "empty message")
                        continue
                    kind = message[0]
                    if kind == 1:  # audio
                        payload = message[1:]
                        opus_reader.append_bytes(payload)
                    else:
                        clog.log("warning", f"unknown message kind {kind}")
            finally:
                close = True
                clog.log("info", "connection closed")

        async def opus_loop():
            all_pcm_data = None

            while True:
                if close:
                    return
                await asyncio.sleep(0.001)
                pcm = opus_reader.read_pcm()
                if pcm.shape[-1] == 0:
                    continue
                if all_pcm_data is None:
                    all_pcm_data = pcm
                else:
                    all_pcm_data = np.concatenate((all_pcm_data, pcm))
                while all_pcm_data.shape[-1] >= self.frame_size:
                    be = time.time()
                    chunk = all_pcm_data[: self.frame_size]
                    all_pcm_data = all_pcm_data[self.frame_size:]
                    chunk = torch.from_numpy(chunk)
                    chunk = chunk.to(device=self.device)[None, None]
                    codes = self.mimi.encode(chunk)
                    _ = self.other_mimi.encode(chunk)
                    for c in range(codes.shape[-1]):
                        tokens = self.lm_gen.step(codes[:, :, c: c + 1])
                        if tokens is None:
                            continue
                        assert tokens.shape[1] == self.lm_gen.lm_model.dep_q + 1
                        main_pcm = self.mimi.decode(tokens[:, 1:9])
                        _ = self.other_mimi.decode(tokens[:, 1:9])
                        main_pcm = main_pcm.cpu()
                        opus_writer.append_pcm(main_pcm[0, 0].numpy())
                        text_token = tokens[0, 0, 0].item()
                        if text_token not in (0, 3):
                            _text = self.text_tokenizer.id_to_piece(text_token)  # type: ignore
                            _text = _text.replace("▁", " ")
                            msg = b"\x02" + bytes(_text, encoding="utf8")
                            await ws.send_bytes(msg)
                        else:
                            text_token_map = ['EPAD', 'BOS', 'EOS', 'PAD']
                            label = (
                                text_token_map[text_token]
                                if text_token < len(text_token_map)
                                else f"UNK({text_token})"
                            )
                            await ws.send_bytes(b"\x03" + bytes(label, encoding="utf8"))

        async def send_loop():
            while True:
                if close:
                    return
                await asyncio.sleep(0.001)
                msg = opus_writer.read_bytes()
                if len(msg) > 0:
                    await ws.send_bytes(b"\x01" + msg)

        clog.log("info", "accepted connection")
        if agent_id:
            clog.log("info", f"agent_id: {agent_id}")
        if len(text_prompt) > 0:
            clog.log("info", f"text prompt: {text_prompt}")
        if len(voice_prompt_filename) > 0:
            clog.log("info", f"voice prompt: {voice_prompt_path} (requested: {requested_voice_prompt_path})")
        close = False
        async with self.lock:
            if self.lm_gen.voice_prompt != voice_prompt_path:
                if voice_prompt_path is None:
                    self.lm_gen.voice_prompt = None
                    self.lm_gen.voice_prompt_audio = None
                    self.lm_gen.voice_prompt_cache = None
                    self.lm_gen.voice_prompt_embeddings = None
                elif voice_prompt_path.endswith('.pt'):
                    # Load pre-saved voice prompt embeddings
                    self.lm_gen.load_voice_prompt_embeddings(voice_prompt_path)
                else:
                    self.lm_gen.load_voice_prompt(voice_prompt_path)

            self.lm_gen.text_prompt_tokens = (
                self.text_tokenizer.encode(wrap_with_system_tags(text_prompt))
                if len(text_prompt) > 0 else None
            )

            if seed is not None and seed != -1:
                seed_all(seed)

            opus_writer = sphn.OpusStreamWriter(self.mimi.sample_rate)
            opus_reader = sphn.OpusStreamReader(self.mimi.sample_rate)
            self.mimi.reset_streaming()
            self.other_mimi.reset_streaming()
            self.lm_gen.reset_streaming()
            async def is_alive():
                if close or ws.closed:
                    return False
                try:
                    # Check for disconnect without waiting too long
                    msg = await asyncio.wait_for(ws.receive(), timeout=0.01)
                    if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        return False
                except asyncio.TimeoutError:
                    # No messages → client probably still alive
                    return True
                except aiohttp.ClientConnectionError:
                    return False
                return True
            # Reuse mimi for encoding voice prompt and then reset it before conversation starts
            await self.lm_gen.step_system_prompts_async(self.mimi, is_alive=is_alive)
            self.mimi.reset_streaming()
            clog.log("info", "done with system prompts")
            # Send the handshake.
            if await is_alive():
                await ws.send_bytes(b"\x00")
                clog.log("info", "sent handshake bytes")
                # Clean cancellation manager
                tasks = [
                    asyncio.create_task(recv_loop()),
                    asyncio.create_task(opus_loop()),
                    asyncio.create_task(send_loop()),
                ]

                done, pending = await asyncio.wait(
                    tasks,
                    return_when=asyncio.FIRST_COMPLETED,
                    timeout=3600.0,
                )
                if not done:
                    clog.log("warning", "session timeout reached, terminating tasks")
                # Force-kill remaining tasks
                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                await ws.close()
                clog.log("info", "session closed")
                # await asyncio.gather(opus_loop(), recv_loop(), send_loop())
        clog.log("info", "done with connection")
        return ws

    async def handle_agents(self, request):
        expected_token = os.environ.get("MOSHI_API_TOKEN", "")
        if expected_token:
            auth_token = request.query.get("token")
            if not auth_token:
                auth_header = request.headers.get("Authorization", "")
                if auth_header.startswith("Bearer "):
                    auth_token = auth_header[len("Bearer "):].strip()
            if auth_token != expected_token:
                return web.Response(status=401, text="Unauthorized")

        try:
            omni_bearer = request.query.get("omni_bearer", "").strip()
            omni_user_id = request.query.get("omni_user_id", "").strip()
            agents = await self.fetch_agents(
                api_key_override=omni_bearer,
                user_id_override=omni_user_id,
            )
            return web.json_response({"agents": agents})
        except Exception as error:
            if "Authorization Bearer token missing" in str(error):
                return web.json_response(
                    {"agents": [], "error": "OmniCortex bearer token missing"},
                    status=200,
                )
            logger.error("failed to fetch agents from OmniCortex: %s", error)
            return web.json_response({"agents": [], "error": str(error)}, status=500)

    async def handle_agent_prompt(self, request):
        expected_token = os.environ.get("MOSHI_API_TOKEN", "")
        if expected_token:
            auth_token = request.query.get("token")
            if not auth_token:
                auth_header = request.headers.get("Authorization", "")
                if auth_header.startswith("Bearer "):
                    auth_token = auth_header[len("Bearer "):].strip()
            if auth_token != expected_token:
                return web.Response(status=401, text="Unauthorized")

        agent_id = request.query.get("agent_id", "").strip()
        if not agent_id:
            return web.json_response(
                {"prompt": "", "error": "agent_id is required"},
                status=400,
            )

        context_query = request.query.get("context_query", "").strip()
        omni_bearer = request.query.get("omni_bearer", "").strip()
        omni_user_id = request.query.get("omni_user_id", "").strip()
        try:
            prompt = await self.fetch_agent_prompt(
                agent_id=agent_id,
                context_query=context_query,
                api_key_override=omni_bearer,
                user_id_override=omni_user_id,
            )
            return web.json_response({"agent_id": agent_id, "prompt": prompt})
        except Exception as error:
            if "Authorization Bearer token missing" in str(error):
                return web.json_response(
                    {"agent_id": agent_id, "prompt": "", "error": "OmniCortex bearer token missing"},
                    status=200,
                )
            logger.error("failed to fetch agent prompt from OmniCortex: %s", error)
            return web.json_response(
                {"agent_id": agent_id, "prompt": "", "error": str(error)},
                status=500,
            )

    async def handle_agent_details(self, request):
        expected_token = os.environ.get("MOSHI_API_TOKEN", "")
        if expected_token:
            auth_token = request.query.get("token")
            if not auth_token:
                auth_header = request.headers.get("Authorization", "")
                if auth_header.startswith("Bearer "):
                    auth_token = auth_header[len("Bearer "):].strip()
            if auth_token != expected_token:
                return web.Response(status=401, text="Unauthorized")

        agent_id = request.query.get("agent_id", "").strip()
        if not agent_id:
            return web.json_response({"agent": {}, "error": "agent_id is required"}, status=400)

        omni_bearer = request.query.get("omni_bearer", "").strip()
        omni_user_id = request.query.get("omni_user_id", "").strip()
        try:
            agent = await self.fetch_agent_detail(
                agent_id=agent_id,
                api_key_override=omni_bearer,
                user_id_override=omni_user_id,
            )
            return web.json_response({"agent": agent})
        except Exception as error:
            if "Authorization Bearer token missing" in str(error):
                return web.json_response(
                    {"agent": {}, "error": "OmniCortex bearer token missing"},
                    status=200,
                )
            logger.error("failed to fetch agent details from OmniCortex: %s", error)
            return web.json_response({"agent": {}, "error": str(error)}, status=500)

    async def handle_voice_profile(self, request):
        expected_token = os.environ.get("MOSHI_API_TOKEN", "")
        if expected_token:
            auth_token = request.query.get("token")
            if not auth_token:
                auth_header = request.headers.get("Authorization", "")
                if auth_header.startswith("Bearer "):
                    auth_token = auth_header[len("Bearer "):].strip()
            if auth_token != expected_token:
                return web.Response(status=401, text="Unauthorized")

        omni_bearer = request.query.get("omni_bearer", "").strip()
        omni_user_id = request.query.get("omni_user_id", "").strip()
        try:
            if request.method == "GET":
                profile = await self.fetch_voice_profile(
                    api_key_override=omni_bearer,
                    user_id_override=omni_user_id,
                )
                return web.json_response({"status": "ok", "profile": profile})

            payload = await request.json()
            if not isinstance(payload, dict):
                payload = {}
            profile = await self.save_voice_profile(
                payload,
                api_key_override=omni_bearer,
                user_id_override=omni_user_id,
            )
            return web.json_response({"status": "saved", "profile": profile})
        except Exception as error:
            if "Authorization Bearer token missing" in str(error):
                return web.json_response(
                    {"status": "error", "profile": {}, "error": "OmniCortex bearer token missing"},
                    status=200,
                )
            logger.error("voice profile sync with OmniCortex failed: %s", error)
            return web.json_response(
                {"status": "error", "profile": {}, "error": str(error)},
                status=500,
            )


def _get_voice_prompt_dir(voice_prompt_dir: Optional[str], hf_repo: str) -> Optional[str]:
    """
    If voice_prompt_dir is None:
      - download voices.tgz from HF
      - extract it once
      - return extracted directory
    If voice_prompt_dir is provided:
      - just return it
    """
    if voice_prompt_dir is not None:
        return voice_prompt_dir

    logger.info("retrieving voice prompts")

    voices_tgz = hf_hub_download(hf_repo, "voices.tgz")
    voices_tgz = Path(voices_tgz)
    voices_dir = voices_tgz.parent / "voices"

    if not voices_dir.exists():
        logger.info(f"extracting {voices_tgz} to {voices_dir}")
        with tarfile.open(voices_tgz, "r:gz") as tar:
            tar.extractall(path=voices_tgz.parent)

    if not voices_dir.exists():
        raise RuntimeError("voices.tgz did not contain a 'voices/' directory")

    return str(voices_dir)


def _get_static_path(static: Optional[str]) -> Optional[str]:
    if static is None:
        logger.info("retrieving the static content")
        dist_tgz = hf_hub_download("nvidia/personaplex-7b-v1", "dist.tgz")
        dist_tgz = Path(dist_tgz)
        dist = dist_tgz.parent / "dist"
        if not dist.exists():
            with tarfile.open(dist_tgz, "r:gz") as tar:
                tar.extractall(path=dist_tgz.parent)
        return str(dist)
    elif static != "none":
        # When set to the "none" string, we don't serve any static content.
        return static
    return None


def _customized_index_html(static_path: str, has_server_omnicortex_key: bool = False) -> str:
    index_path = os.path.join(static_path, "index.html")
    with open(index_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Runtime branding override for upstream PersonaPlex static bundle.
    branding_replacements = {
        "PersonaPlex": "OmniCortex",
        "Full-duplex conversational AI with text and voice control.": "Full duplex conversational AI with text and voice control.",
    }
    for source_text, target_text in branding_replacements.items():
        content = content.replace(source_text, target_text)

    token = os.getenv("MOSHI_API_TOKEN", "").strip()
    token_js_literal = json.dumps(token)
    has_server_omni_key_js = "true" if has_server_omnicortex_key else "false"

    # Inject UI patch:
    # - replace stock "Examples" chips with OmniCortex "Agents" chips
    # - fill Text Prompt using RAG-backed agent prompt
    # - ensure /api/chat websocket carries selected agent_id
    injection = f"""
<script>
(() => {{
  const MOSHI_TOKEN = {token_js_literal};
  const HAS_SERVER_OMNI_KEY = {has_server_omni_key_js};
  const AGENT_KEY = "personaplex_agent_id";
  const OMNI_BEARER_KEY = "omnicortex_bearer_token";
  const CONTEXT_QUERY_KEY = "omnicortex_context_query";
  let PROFILE_INITIALIZED = false;
  let AGENT_CACHE = [];
  let SEARCH_TIMER = null;
        const OriginalWebSocket = window.WebSocket;

  function ensureUiStyles() {{
    if (document.getElementById("omnicortex-agent-style")) return;
    const style = document.createElement("style");
    style.id = "omnicortex-agent-style";
    style.textContent = `
      #omnicortex-agent-controls {{
        margin: 8px 0 10px;
        border: 1px solid #d9d9de;
        border-radius: 10px;
        background: #f7f8fb;
        padding: 10px;
      }}
      #omnicortex-agent-controls .omni-row {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 8px;
        margin-bottom: 8px;
      }}
      #omnicortex-agent-controls .omni-row.full {{
        grid-template-columns: 1fr;
      }}
      #omnicortex-agent-controls input {{
        width: 100%;
        padding: 6px 9px;
        border-radius: 8px;
        border: 1px solid #c5c8d0;
        font-size: 12px;
        box-sizing: border-box;
      }}
      #omnicortex-agent-controls .omni-actions {{
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
      }}
      #omnicortex-agent-controls button {{
        border: 1px solid #1f2937;
        border-radius: 8px;
        background: #111827;
        color: #fff;
        padding: 6px 10px;
        font-size: 12px;
        cursor: pointer;
      }}
      #omnicortex-agent-controls button.secondary {{
        background: #fff;
        color: #111827;
      }}
      #omnicortex-agent-chips {{
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
        gap: 8px;
      }}
      .omni-agent-card {{
        text-align: left;
        padding: 10px;
        border: 1px solid #d2d6df;
        border-radius: 10px;
        background: #ffffff;
        cursor: pointer;
      }}
      .omni-agent-card.omni-agent-active {{
        border-color: #76b900;
        box-shadow: 0 0 0 2px rgba(118, 185, 0, 0.25);
        background: #f7ffec;
      }}
      .omni-agent-name {{
        display: block;
        font-size: 13px;
        font-weight: 600;
        margin-bottom: 4px;
      }}
      .omni-agent-meta {{
        display: block;
        font-size: 11px;
        color: #6b7280;
      }}
    `;
    document.head.appendChild(style);
  }}

  function escapeHtml(value) {{
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }}

  function withToken(url) {{
    if (!MOSHI_TOKEN) return url;
    try {{
      const u = new URL(url, window.location.href);
      u.searchParams.set("token", MOSHI_TOKEN);
      return u.toString();
    }} catch (_e) {{
      return url;
    }}
  }}

  function selectedAgentId() {{
    const select = document.getElementById("omnicortex-agent-select");
    const fromUi = select && select.value ? select.value : "";
    if (fromUi) {{
      localStorage.setItem(AGENT_KEY, fromUi);
      return fromUi;
    }}
    return localStorage.getItem(AGENT_KEY) || "";
  }}

  function currentOmniBearer() {{
    const input = document.getElementById("omnicortex-bearer-token");
    if (input) {{
      const fromUi = input.value ? input.value.trim() : "";
      if (fromUi) {{
        localStorage.setItem(OMNI_BEARER_KEY, fromUi);
      }} else {{
        localStorage.removeItem(OMNI_BEARER_KEY);
      }}
      return fromUi;
    }}
    if (HAS_SERVER_OMNI_KEY) return "";
    return localStorage.getItem(OMNI_BEARER_KEY) || "";
  }}

  function currentContextQuery() {{
    const input = document.getElementById("omnicortex-context-query");
    if (input) {{
      const fromUi = input.value ? input.value.trim() : "";
      if (fromUi) {{
        localStorage.setItem(CONTEXT_QUERY_KEY, fromUi);
      }} else {{
        localStorage.removeItem(CONTEXT_QUERY_KEY);
      }}
      return fromUi;
    }}
    return localStorage.getItem(CONTEXT_QUERY_KEY) || "";
  }}

  window.WebSocket = function patchedWebSocket(url, protocols) {{
    let nextUrl = url;
    try {{
      const u = new URL(url, window.location.href);
      if (u.pathname === "/api/chat") {{
        const aid = selectedAgentId();
        if (aid) {{
          u.searchParams.set("agent_id", aid);
        }}
        const omniBearer = currentOmniBearer();
        if (omniBearer) {{
          u.searchParams.set("omni_bearer", omniBearer);
        }}
        const seedQuery = currentContextQuery();
        if (seedQuery) {{
          u.searchParams.set("context_query", seedQuery.slice(0, 400));
        }} else {{
          const promptArea = textPromptTextarea();
          const fallbackQuery = promptArea && promptArea.value ? promptArea.value.trim() : "";
          if (fallbackQuery) {{
            u.searchParams.set("context_query", fallbackQuery.slice(0, 400));
          }}
        }}
        u.searchParams.delete("text_prompt");
      }}
      nextUrl = withToken(u.toString());
    }} catch (_e) {{
      nextUrl = withToken(url);
    }}
    return protocols === undefined
      ? new OriginalWebSocket(nextUrl)
      : new OriginalWebSocket(nextUrl, protocols);
  }};
  window.WebSocket.prototype = OriginalWebSocket.prototype;
  window.__omni_ws_patched = true;

  function textPromptTextarea() {{
    return (
      document.getElementById("text-prompt") ||
      document.querySelector("textarea[name='text_prompt']") ||
      document.querySelector("textarea")
    );
  }}

  function setTextPrompt(value) {{
    const area = textPromptTextarea();
    if (!area) return;
    area.value = value || "";
    area.dispatchEvent(new Event("input", {{ bubbles: true }}));
    area.dispatchEvent(new Event("change", {{ bubbles: true }}));
  }}

  function voicePromptSelect() {{
    return (
      document.querySelector("select[name='voice_prompt']") ||
      document.querySelector("select")
    );
  }}

  async function loadAgentPrompt(agentId, contextQuery) {{
    if (!agentId) return "";
    const endpoint = new URL("/api/agent-prompt", window.location.origin);
    if (MOSHI_TOKEN) {{
      endpoint.searchParams.set("token", MOSHI_TOKEN);
    }}
    endpoint.searchParams.set("agent_id", agentId);
    if (contextQuery) {{
      endpoint.searchParams.set("context_query", contextQuery);
    }}
    const omniBearer = currentOmniBearer();
    if (omniBearer) {{
      endpoint.searchParams.set("omni_bearer", omniBearer);
    }}
    const res = await fetch(endpoint.toString(), {{ cache: "no-store" }});
    const json = await res.json();
    return typeof json.prompt === "string" ? json.prompt : "";
  }}

  async function loadAgents() {{
    if (!HAS_SERVER_OMNI_KEY && !currentOmniBearer()) {{
      throw new Error("OmniCortex bearer token is required");
    }}
    const endpoint = new URL("/api/agents", window.location.origin);
    if (MOSHI_TOKEN) {{
      endpoint.searchParams.set("token", MOSHI_TOKEN);
    }}
    const omniBearer = currentOmniBearer();
    if (omniBearer) {{
      endpoint.searchParams.set("omni_bearer", omniBearer);
    }}
    const res = await fetch(endpoint.toString(), {{ cache: "no-store" }});
    const json = await res.json().catch(() => ({{}}));
    if (!res.ok) {{
      const reason = (json && json.error) ? json.error : `HTTP ${{res.status}}`;
      throw new Error(reason);
    }}
    if (json && json.error) {{
      throw new Error(String(json.error));
    }}
    return Array.isArray(json.agents) ? json.agents : [];
  }}

  async function loadAgentDetails(agentId) {{
    if (!agentId) return {{}};
    const endpoint = new URL("/api/agent-details", window.location.origin);
    if (MOSHI_TOKEN) {{
      endpoint.searchParams.set("token", MOSHI_TOKEN);
    }}
    endpoint.searchParams.set("agent_id", agentId);
    const omniBearer = currentOmniBearer();
    if (omniBearer) {{
      endpoint.searchParams.set("omni_bearer", omniBearer);
    }}
    const res = await fetch(endpoint.toString(), {{ cache: "no-store" }});
    const json = await res.json().catch(() => ({{}}));
    if (!res.ok) {{
      const reason = (json && json.error) ? json.error : `HTTP ${{res.status}}`;
      throw new Error(reason);
    }}
    if (json && json.error) {{
      throw new Error(String(json.error));
    }}
    return (json && typeof json.agent === "object" && json.agent) ? json.agent : {{}};
  }}

  async function loadVoiceProfile() {{
    const endpoint = new URL("/api/voice-profile", window.location.origin);
    if (MOSHI_TOKEN) {{
      endpoint.searchParams.set("token", MOSHI_TOKEN);
    }}
    const omniBearer = currentOmniBearer();
    if (omniBearer) {{
      endpoint.searchParams.set("omni_bearer", omniBearer);
    }}
    const res = await fetch(endpoint.toString(), {{ cache: "no-store" }});
    const json = await res.json().catch(() => ({{}}));
    if (!res.ok) {{
      const reason = (json && json.error) ? json.error : `HTTP ${{res.status}}`;
      throw new Error(reason);
    }}
    if (json && json.error) {{
      throw new Error(String(json.error));
    }}
    const profile = (json && typeof json.profile === "object" && json.profile) ? json.profile : {{}};
    return profile;
  }}

  async function saveVoiceProfile(payload) {{
    const endpoint = new URL("/api/voice-profile", window.location.origin);
    if (MOSHI_TOKEN) {{
      endpoint.searchParams.set("token", MOSHI_TOKEN);
    }}
    const omniBearer = currentOmniBearer();
    if (omniBearer) {{
      endpoint.searchParams.set("omni_bearer", omniBearer);
    }}
    const res = await fetch(endpoint.toString(), {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify(payload || {{}}),
    }});
    const json = await res.json().catch(() => ({{}}));
    if (!res.ok) {{
      const reason = (json && json.error) ? json.error : `HTTP ${{res.status}}`;
      throw new Error(reason);
    }}
    if (json && json.error) {{
      throw new Error(String(json.error));
    }}
    return (json && typeof json.profile === "object" && json.profile) ? json.profile : {{}};
  }}

  function renderAgentDetails(ui, agent) {{
    let panel = ui.panel.querySelector("#omnicortex-agent-details");
    if (!panel) {{
      panel = document.createElement("div");
      panel.id = "omnicortex-agent-details";
      panel.style.cssText = "margin:8px 0 10px;padding:10px;border:1px solid #d2d6df;border-radius:10px;font-size:12px;line-height:1.6;background:#ffffff;";
      ui.panel.appendChild(panel);
    }}
    if (!agent || !agent.id) {{
      panel.style.display = "none";
      panel.innerHTML = "";
      return;
    }}

    const docs = Array.isArray(agent.documents) ? agent.documents : [];
    const docNames = docs
      .map((d) => (d && d.filename) ? String(d.filename) : "")
      .filter(Boolean)
      .slice(0, 8);
    const normalizePromptPreview = (items) => (Array.isArray(items) ? items : [])
      .slice(0, 3)
      .map((item) => {{
        if (typeof item === "string") return item;
        if (item && typeof item === "object") {{
          if (typeof item.prompt === "string" && item.prompt.trim()) return item.prompt.trim();
          if (typeof item.label === "string" && item.label.trim()) return item.label.trim();
        }}
        return "";
      }})
      .filter(Boolean);
    const startPreview = normalizePromptPreview(agent.conversation_starters);
    const endPreview = normalizePromptPreview(agent.conversation_end);

    panel.style.display = "block";
    panel.innerHTML = `
      <div style="font-weight:700;margin-bottom:6px;color:#111827;">Selected Agent</div>
      <div><b>Name:</b> ${{escapeHtml(agent.name || "-")}}</div>
      <div><b>ID:</b> <code>${{escapeHtml(agent.id || "-")}}</code></div>
      <div><b>Type:</b> ${{escapeHtml(agent.agent_type || "-")}}</div>
      <div><b>Documents:</b> ${{agent.document_count || 0}}</div>
      <div><b>Web URLs:</b> ${{Array.isArray(agent.urls) ? agent.urls.length : 0}}</div>
      <div><b>Images:</b> ${{Array.isArray(agent.image_urls) ? agent.image_urls.length : 0}}</div>
      <div><b>Videos:</b> ${{Array.isArray(agent.video_urls) ? agent.video_urls.length : 0}}</div>
      <div><b>Sample docs:</b> ${{docNames.length ? escapeHtml(docNames.join(", ")) : "-"}}</div>
      <div><b>Conversation starters:</b> ${{startPreview.length ? escapeHtml(startPreview.join(" | ")) : "-"}}</div>
      <div><b>Conversation end:</b> ${{endPreview.length ? escapeHtml(endPreview.join(" | ")) : "-"}}</div>
    `;
  }}

  function findExamplesUi() {{
    const sampleTexts = new Set([
      "assistant (default)",
      "medical office (service)",
      "bank (service)",
      "astronaut (fun)",
    ]);
    const allButtons = Array.from(document.querySelectorAll("button,[role='button']"));
    const sampleButtons = allButtons.filter((btn) =>
      sampleTexts.has((btn.textContent || "").trim().toLowerCase()),
    );
    if (sampleButtons.length) {{
      const chipsWrap = sampleButtons[0].parentElement;
      if (!chipsWrap) return null;
      const panel = chipsWrap.parentElement;
      if (!panel) return null;
      const marker = Array.from(panel.querySelectorAll("span,strong,div,p,label")).find(
        (node) => (node.textContent || "").trim().toLowerCase() === "examples:",
      );
      return {{
        panel,
        chipsWrap,
        marker,
        buttonClass: sampleButtons[0].className || "",
      }};
    }}

    // Fallback for UI variants where "Examples" chips are rendered differently.
    const marker = Array.from(document.querySelectorAll("span,strong,div,p,label")).find(
      (node) => (node.textContent || "").trim().toLowerCase() === "examples:",
    );
    if (marker) {{
      const panel = marker.closest("div") || marker.parentElement;
      if (panel) {{
        const chipsWrap = Array.from(panel.querySelectorAll("div")).find((container) => {{
          const labels = Array.from(container.querySelectorAll("button,[role='button']")).map(
            (btn) => (btn.textContent || "").trim().toLowerCase(),
          );
          return labels.some((label) => sampleTexts.has(label));
        }});
        if (chipsWrap) {{
          const firstBtn = chipsWrap.querySelector("button,[role='button']");
          return {{
            panel,
            chipsWrap,
            marker,
            buttonClass: firstBtn ? firstBtn.className || "" : "",
          }};
        }}
      }}
    }}

    return null;
  }}

  function highlightActiveAgent(chipsWrap, agentId) {{
    const all = Array.from(chipsWrap.querySelectorAll("button[data-agent-id]"));
    for (const btn of all) {{
      const selected = btn.dataset.agentId === agentId;
      btn.classList.toggle("omni-agent-active", selected);
      btn.setAttribute("aria-pressed", selected ? "true" : "false");
    }}
  }}

  function matchesAgentSearch(agent, query) {{
    if (!query) return true;
    const q = String(query || "").toLowerCase();
    const name = String(agent?.name || "").toLowerCase();
    const type = String(agent?.type || "").toLowerCase();
    const id = String(agent?.id || "").toLowerCase();
    return name.includes(q) || type.includes(q) || id.includes(q);
  }}

  async function activateAgent(ui, agentId, loadPrompt) {{
    if (!agentId) return;
    const status = ui.panel.querySelector("#omnicortex-agent-status");
    const error = ui.panel.querySelector("#omnicortex-agent-error");
    localStorage.setItem(AGENT_KEY, agentId);
    highlightActiveAgent(ui.chipsWrap, agentId);
    if (status) {{
      status.style.display = "none";
      status.textContent = "";
    }}
    if (error) {{
      error.style.display = "none";
      error.textContent = "";
    }}
    try {{
      if (loadPrompt) {{
        const seed = (currentContextQuery() || (textPromptTextarea()?.value || "")).trim().slice(0, 400);
        const prompt = await loadAgentPrompt(agentId, seed);
        if (prompt) setTextPrompt(prompt);
      }}
      const detail = await loadAgentDetails(agentId);
      renderAgentDetails(ui, detail);
      if (status) {{
        status.textContent = loadPrompt
          ? "Agent ready. You can start speaking now."
          : "Agent selected. Click 'Start With Selected Agent' to load prompt.";
        status.style.display = "block";
      }}
    }} catch (err) {{
      renderAgentDetails(ui, {{}});
      if (error) {{
        const msg = (err && err.message) ? err.message : String(err || "Unknown error");
        error.textContent = `Agent activation failed: ${{msg}}`;
        error.style.display = "block";
      }}
    }}
  }}

  function ensureAgentControls(ui, onRefresh) {{
    ensureUiStyles();
    let controls = ui.panel.querySelector("#omnicortex-agent-controls");
    if (!controls) {{
      controls = document.createElement("div");
      controls.id = "omnicortex-agent-controls";
      const tokenRow = document.createElement("div");
      tokenRow.className = "omni-row";
      const input = document.createElement("input");
      input.id = "omnicortex-bearer-token";
      input.type = "password";
      input.placeholder = HAS_SERVER_OMNI_KEY
        ? "Bearer token (optional override)"
        : "Bearer token";
      input.value = HAS_SERVER_OMNI_KEY ? "" : (localStorage.getItem(OMNI_BEARER_KEY) || "");
      const contextInput = document.createElement("input");
      contextInput.id = "omnicortex-context-query";
      contextInput.type = "text";
      contextInput.placeholder = "RAG context query (e.g. github)";
      contextInput.value = localStorage.getItem(CONTEXT_QUERY_KEY) || "";
      tokenRow.appendChild(input);
      tokenRow.appendChild(contextInput);
      controls.appendChild(tokenRow);

      const searchRow = document.createElement("div");
      searchRow.className = "omni-row full";
      const searchInput = document.createElement("input");
      searchInput.id = "omnicortex-agent-search";
      searchInput.type = "text";
      searchInput.placeholder = "Search by agent name, type, or id";
      searchRow.appendChild(searchInput);
      controls.appendChild(searchRow);

      const actions = document.createElement("div");
      actions.className = "omni-actions";
      const refresh = document.createElement("button");
      refresh.id = "omnicortex-agent-refresh";
      refresh.type = "button";
      refresh.textContent = "Refresh Agents";
      refresh.className = "secondary";
      actions.appendChild(refresh);
      const start = document.createElement("button");
      start.id = "omnicortex-agent-start";
      start.type = "button";
      start.textContent = "Start With Selected Agent";
      actions.appendChild(start);
      const save = document.createElement("button");
      save.id = "omnicortex-agent-save";
      save.type = "button";
      save.textContent = "Save Profile";
      save.className = "secondary";
      actions.appendChild(save);
      controls.appendChild(actions);
      ui.panel.insertBefore(controls, ui.chipsWrap);
    }}

    ui.chipsWrap.id = "omnicortex-agent-chips";

    let errorRow = ui.panel.querySelector("#omnicortex-agent-error");
    if (!errorRow) {{
      errorRow = document.createElement("div");
      errorRow.id = "omnicortex-agent-error";
      errorRow.style.cssText = "margin:4px 0 8px;color:#b00020;font-size:12px;text-align:center;display:none;";
      ui.panel.insertBefore(errorRow, ui.chipsWrap);
    }}

    let statusRow = ui.panel.querySelector("#omnicortex-agent-status");
    if (!statusRow) {{
      statusRow = document.createElement("div");
      statusRow.id = "omnicortex-agent-status";
      statusRow.style.cssText = "margin:2px 0 8px;color:#2e7d32;font-size:12px;text-align:center;display:none;";
      ui.panel.insertBefore(statusRow, ui.chipsWrap);
    }}

    const tokenInput = controls.querySelector("#omnicortex-bearer-token");
    if (tokenInput && !tokenInput.dataset.bound) {{
      tokenInput.addEventListener("change", () => {{
        const value = tokenInput.value ? tokenInput.value.trim() : "";
        if (value) {{
          localStorage.setItem(OMNI_BEARER_KEY, value);
        }} else {{
          localStorage.removeItem(OMNI_BEARER_KEY);
        }}
        onRefresh().catch(console.error);
      }});
      tokenInput.dataset.bound = "1";
    }}

    const contextInput = controls.querySelector("#omnicortex-context-query");
    if (contextInput && !contextInput.dataset.bound) {{
      contextInput.addEventListener("change", () => {{
        const value = contextInput.value ? contextInput.value.trim() : "";
        if (value) {{
          localStorage.setItem(CONTEXT_QUERY_KEY, value);
        }} else {{
          localStorage.removeItem(CONTEXT_QUERY_KEY);
        }}
      }});
      contextInput.dataset.bound = "1";
    }}

    const searchInput = controls.querySelector("#omnicortex-agent-search");
    if (searchInput && !searchInput.dataset.bound) {{
      searchInput.addEventListener("input", () => {{
        if (SEARCH_TIMER) window.clearTimeout(SEARCH_TIMER);
        SEARCH_TIMER = window.setTimeout(() => {{
          onRefresh().catch(console.error);
        }}, 120);
      }});
      searchInput.dataset.bound = "1";
    }}

    const refreshBtn = controls.querySelector("#omnicortex-agent-refresh");
    if (refreshBtn && !refreshBtn.dataset.bound) {{
      refreshBtn.addEventListener("click", () => onRefresh().catch(console.error));
      refreshBtn.dataset.bound = "1";
    }}

    const startBtn = controls.querySelector("#omnicortex-agent-start");
    if (startBtn && !startBtn.dataset.bound) {{
      startBtn.addEventListener("click", async () => {{
        await activateAgent(ui, selectedAgentId(), true);
      }});
      startBtn.dataset.bound = "1";
    }}

    const saveBtn = controls.querySelector("#omnicortex-agent-save");
    if (saveBtn && !saveBtn.dataset.bound) {{
      saveBtn.addEventListener("click", async () => {{
        const status = ui.panel.querySelector("#omnicortex-agent-status");
        const error = ui.panel.querySelector("#omnicortex-agent-error");
        if (status) {{
          status.style.display = "none";
          status.textContent = "";
        }}
        if (error) {{
          error.style.display = "none";
          error.textContent = "";
        }}
        try {{
          const voiceSel = voicePromptSelect();
          const payload = {{
            api_key: currentOmniBearer(),
            selected_agent_id: selectedAgentId() || null,
            context_query: currentContextQuery(),
            voice_prompt: voiceSel && voiceSel.value ? String(voiceSel.value) : "NATF0.pt",
            extra: {{ source: "personaplex_ui" }},
          }};
          await saveVoiceProfile(payload);
          if (status) {{
            status.textContent = "Voice profile saved in PostgreSQL";
            status.style.display = "block";
          }}
        }} catch (err) {{
          const msg = (err && err.message) ? err.message : String(err || "Unknown error");
          if (error) {{
            error.textContent = `Save failed: ${{msg}}`;
            error.style.display = "block";
          }}
        }}
      }});
      saveBtn.dataset.bound = "1";
    }}
  }}

  async function patchExamplesToAgents() {{
    const ui = findExamplesUi();
    if (!ui) return;
    if (ui.marker) {{
      ui.marker.textContent = "Agents:";
    }}

    ensureAgentControls(ui, patchExamplesToAgents);
    const tokenInput = ui.panel.querySelector("#omnicortex-bearer-token");
    const contextInput = ui.panel.querySelector("#omnicortex-context-query");
    const statusRow = ui.panel.querySelector("#omnicortex-agent-status");
    const errorRow = ui.panel.querySelector("#omnicortex-agent-error");
    if (!PROFILE_INITIALIZED) {{
      PROFILE_INITIALIZED = true;
      try {{
        const profile = await loadVoiceProfile();
        if (profile && typeof profile === "object") {{
          if (tokenInput && !tokenInput.value && profile.api_key) {{
            tokenInput.value = String(profile.api_key);
          }}
          if (contextInput && !contextInput.value && profile.context_query) {{
            contextInput.value = String(profile.context_query);
            localStorage.setItem(CONTEXT_QUERY_KEY, String(profile.context_query));
          }}
          if (profile.selected_agent_id) {{
            localStorage.setItem(AGENT_KEY, String(profile.selected_agent_id));
          }}
          const voiceSel = voicePromptSelect();
          if (voiceSel && profile.voice_prompt) {{
            const wanted = String(profile.voice_prompt);
            const option = Array.from(voiceSel.options || []).find((o) => String(o.value) === wanted);
            if (option) {{
              voiceSel.value = wanted;
            }}
          }}
          if (statusRow && (profile.has_api_key || profile.api_key_preview)) {{
            statusRow.textContent = "Loaded saved voice profile from PostgreSQL";
            statusRow.style.display = "block";
          }}
        }}
      }} catch (err) {{
        if (errorRow) {{
          const msg = (err && err.message) ? err.message : String(err || "Unknown error");
          errorRow.textContent = `Profile load failed: ${{msg}}`;
          errorRow.style.display = "block";
        }}
      }}
    }}

    if (errorRow) {{
      errorRow.textContent = "";
      errorRow.style.display = "none";
    }}
    if (statusRow && statusRow.style.display !== "block") {{
      statusRow.textContent = "";
      statusRow.style.display = "none";
    }}
    let agents = [];
    try {{
      agents = await loadAgents();
      AGENT_CACHE = Array.isArray(agents) ? agents.slice() : [];
    }} catch (err) {{
      if (errorRow) {{
        const msg = (err && err.message) ? err.message : String(err || "Unknown error");
        errorRow.textContent = `Agents load failed: ${{msg}}`;
        errorRow.style.display = "block";
      }}
      agents = [];
      AGENT_CACHE = [];
    }}
    ui.chipsWrap.innerHTML = "";

    if (!AGENT_CACHE.length) {{
      const msg = document.createElement("span");
      msg.style.cssText = "font-size:12px;color:#666;";
      msg.textContent = "No agents available";
      ui.chipsWrap.appendChild(msg);
      return;
    }}

    const searchInput = ui.panel.querySelector("#omnicortex-agent-search");
    const searchTerm = searchInput && searchInput.value ? searchInput.value.trim() : "";
    const visibleAgents = AGENT_CACHE.filter((agent) => matchesAgentSearch(agent, searchTerm));

    if (!visibleAgents.length) {{
      const msg = document.createElement("span");
      msg.style.cssText = "font-size:12px;color:#666;";
      msg.textContent = "No agents match your search";
      ui.chipsWrap.appendChild(msg);
      return;
    }}

    let selected = localStorage.getItem(AGENT_KEY) || "";
    if (!selected || !AGENT_CACHE.some((a) => a.id === selected)) {{
      selected = AGENT_CACHE[0].id;
      localStorage.setItem(AGENT_KEY, selected);
    }}

    for (const agent of visibleAgents) {{
      const btn = document.createElement("button");
      btn.type = "button";
      btn.dataset.agentId = agent.id;
      btn.className = `${{ui.buttonClass || ""}} omni-agent-card`;
      const docCount = Number(agent.document_count || 0);
      const typeText = agent.type ? String(agent.type) : "Unknown";
      btn.innerHTML = `
        <span class="omni-agent-name">${{escapeHtml(agent.name || agent.id)}}</span>
        <span class="omni-agent-meta">${{escapeHtml(typeText)}} · Docs: ${{docCount}}</span>
      `;
      btn.addEventListener("click", async () => {{
        await activateAgent(ui, agent.id, false);
      }});
      ui.chipsWrap.appendChild(btn);
    }}

    highlightActiveAgent(ui.chipsWrap, selected);
    const currentPrompt = (textPromptTextarea()?.value || "").trim();
    if (!currentPrompt) {{
      try {{
        const seed = currentContextQuery().trim().slice(0, 400);
        const prompt = await loadAgentPrompt(selected, seed);
        if (prompt) setTextPrompt(prompt);
      }} catch (err) {{
        console.error(err);
      }}
    }}
    try {{
      await activateAgent(ui, selected, false);
    }} catch (_err) {{
      renderAgentDetails(ui, {{}});
    }}
  }}

  function applyUiPatch() {{
    patchExamplesToAgents().catch(console.error);
  }}

  const observer = new MutationObserver(() => applyUiPatch());
  observer.observe(document.documentElement, {{ childList: true, subtree: true }});
  window.addEventListener("load", applyUiPatch);
  setTimeout(applyUiPatch, 150);
  setTimeout(applyUiPatch, 600);
}})();
</script>
"""
    if "</body>" in content:
        return content.replace("</body>", f"{injection}</body>")
    return content + injection


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="localhost", type=str)
    parser.add_argument("--port", default=8998, type=int)
    parser.add_argument("--static", type=str)
    parser.add_argument("--gradio-tunnel", action='store_true', help='Activate a gradio tunnel.')
    parser.add_argument("--gradio-tunnel-token",
                        help='Provide a custom (secret) token here to keep getting the same URL.')

    parser.add_argument("--tokenizer", type=str, help="Path to a local tokenizer file.")
    parser.add_argument("--moshi-weight", type=str, help="Path to a local checkpoint file for Moshi.")
    parser.add_argument("--mimi-weight", type=str, help="Path to a local checkpoint file for Mimi.")
    parser.add_argument("--hf-repo", type=str, default=loaders.DEFAULT_REPO,
                        help="HF repo to look into, defaults PersonaPlex. "
                             "Use this to select a different pre-trained model.")
    parser.add_argument("--device", type=str, default="cuda", help="Device on which to run, defaults to 'cuda'.")
    parser.add_argument("--cpu-offload", action="store_true",
                        help="Offload LM model layers to CPU when GPU memory is insufficient. "
                             "Requires 'accelerate' package.")
    parser.add_argument(
        "--voice-prompt-dir",
        type=str,
        help=(
            "Directory containing voice prompt files. "
            "If omitted, voices.tgz is downloaded from HF and extracted."
            "Voice prompt filenames from client requests will be joined with this directory path."
        )
    )
    parser.add_argument(
        "--ssl",
        type=str,
        help=(
            "use https instead of http, this flag should point to a directory "
            "that contains valid key.pem and cert.pem files"
        )
    )
    parser.add_argument(
        "--omnicortex-base-url",
        type=str,
        default=os.getenv("OMNICORTEX_BASE_URL", "http://127.0.0.1:8000"),
        help="OmniCortex API base URL (used for agent list and agent prompt lookup).",
    )
    parser.add_argument(
        "--omnicortex-api-key",
        type=str,
        default=os.getenv("OMNICORTEX_API_KEY", os.getenv("MASTER_API_KEY", "")),
        help="OmniCortex bearer API key for server-side requests.",
    )
    parser.add_argument(
        "--omnicortex-user-id",
        type=str,
        default=os.getenv("OMNICORTEX_USER_ID", ""),
        help="Optional x-user-id passed to OmniCortex agent APIs.",
    )
    parser.add_argument(
        "--omnicortex-context-top-k",
        type=int,
        default=int(os.getenv("OMNICORTEX_CONTEXT_TOP_K", "3")),
        help="Top-K chunks for /agents/{id}/voice-context when preparing voice prompts.",
    )
    parser.add_argument(
        "--enable-omnicortex-ui-patch",
        action="store_true",
        default=os.getenv("MOSHI_ENABLE_OMNICORTEX_UI_PATCH", "1").strip().lower()
        in ("1", "true", "yes", "on"),
        help=(
            "Inject custom OmniCortex UI patch into index.html "
            "(agent selector + websocket query patch). Enabled by default; "
            "set MOSHI_ENABLE_OMNICORTEX_UI_PATCH=0 to preserve stock PersonaPlex UI."
        ),
    )

    args = parser.parse_args()
    args.voice_prompt_dir = _get_voice_prompt_dir(
        args.voice_prompt_dir,
        args.hf_repo,
    )
    if args.voice_prompt_dir is not None:
        assert os.path.exists(args.voice_prompt_dir), \
            f"Directory missing: {args.voice_prompt_dir}"
    logger.info(f"voice_prompt_dir = {args.voice_prompt_dir}")

    static_path: None | str = _get_static_path(args.static)
    assert static_path is None or os.path.exists(static_path), \
        f"Static path does not exist: {static_path}."
    logger.info(f"static_path = {static_path}")
    args.device = torch_auto_device(args.device)

    seed_all(42424242)

    setup_tunnel = None
    tunnel_token = ''
    if args.gradio_tunnel:
        try:
            from gradio import networking  # type: ignore
        except ImportError:
            logger.error("Cannot find gradio which is required to activate a tunnel. "
                         "Please install with `pip install gradio`.")
            sys.exit(1)
        setup_tunnel = networking.setup_tunnel
        if args.gradio_tunnel_token is None:
            tunnel_token = secrets.token_urlsafe(32)
        else:
            tunnel_token = args.gradio_tunnel_token

    # Download config.json to increment download counter
    # No worries about double-counting since config.json will be cached the second time
    hf_hub_download(args.hf_repo, "config.json")

    logger.info("loading mimi")
    if args.mimi_weight is None:
        args.mimi_weight = hf_hub_download(args.hf_repo, loaders.MIMI_NAME)
    mimi = loaders.get_mimi(args.mimi_weight, args.device)
    other_mimi = loaders.get_mimi(args.mimi_weight, args.device)
    logger.info("mimi loaded")

    if args.tokenizer is None:
        args.tokenizer = hf_hub_download(args.hf_repo, loaders.TEXT_TOKENIZER_NAME)
    text_tokenizer = sentencepiece.SentencePieceProcessor(args.tokenizer)  # type: ignore

    logger.info("loading moshi")
    if args.moshi_weight is None:
        args.moshi_weight = hf_hub_download(args.hf_repo, loaders.MOSHI_NAME)
    lm = loaders.get_moshi_lm(args.moshi_weight, device=args.device, cpu_offload=args.cpu_offload)
    lm.eval()
    logger.info("moshi loaded")
    state = ServerState(
        mimi=mimi,
        other_mimi=other_mimi,
        text_tokenizer=text_tokenizer,
        lm=lm,
        device=args.device,
        voice_prompt_dir=args.voice_prompt_dir,
        save_voice_prompt_embeddings=False,
        omnicortex_base_url=args.omnicortex_base_url,
        omnicortex_api_key=args.omnicortex_api_key,
        omnicortex_user_id=args.omnicortex_user_id,
        omnicortex_context_top_k=args.omnicortex_context_top_k,
    )
    logger.info("warming up the model")
    state.warmup()
    app = web.Application()
    app.router.add_get("/api/chat", state.handle_chat)
    app.router.add_get("/api/agents", state.handle_agents)
    app.router.add_get("/api/agent-prompt", state.handle_agent_prompt)
    app.router.add_get("/api/agent-details", state.handle_agent_details)
    app.router.add_get("/api/voice-profile", state.handle_voice_profile)
    app.router.add_post("/api/voice-profile", state.handle_voice_profile)
    if static_path is not None:
        if args.enable_omnicortex_ui_patch:
            patched_index = _customized_index_html(
                static_path,
                has_server_omnicortex_key=bool((args.omnicortex_api_key or "").strip()),
            )

            async def handle_root(_):
                return web.Response(text=patched_index, content_type="text/html")
        else:
            async def handle_root(_):
                return web.FileResponse(os.path.join(static_path, "index.html"))

        logger.info(f"serving static content from {static_path}")
        app.router.add_get("/", handle_root)
        app.router.add_static(
            "/", path=static_path, follow_symlinks=True, name="static"
        )
    protocol = "http"
    ssl_context = None
    if args.ssl is not None:
        ssl_context, protocol = create_ssl_context(args.ssl)
    host_ip = args.host if args.host not in ("0.0.0.0", "::", "localhost") else get_lan_ip()
    logger.info(f"Access the Web UI directly at {protocol}://{host_ip}:{args.port}")
    if setup_tunnel is not None:
        tunnel = setup_tunnel('localhost', args.port, tunnel_token, None)
        logger.info(f"Tunnel started, if executing on a remote GPU, you can use {tunnel}.")
    web.run_app(app, port=args.port, ssl_context=ssl_context)


if __name__ == "__main__":
    with torch.no_grad():
        main()
