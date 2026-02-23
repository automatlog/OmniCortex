"use client";

import { useMemo, useState, type ReactNode } from "react";
import { Download, ExternalLink, FileText, Film, Image as ImageIcon, MapPin } from "lucide-react";

const URL_REGEX = /https?:\/\/[^\s<>"{}|\\^`[\]]+/gi;
const IMAGE_EXTS = /\.(png|jpe?g|gif|webp|svg|bmp|ico)(\?.*)?$/i;
const VIDEO_EXTS = /\.(mp4|webm|mov|ogg|avi|mkv)(\?.*)?$/i;
const DOC_EXTS = /\.(pdf|docx?|xlsx?|pptx?|csv|txt|rtf|odt)(\?.*)?$/i;
const MAPS_PATTERNS = [/google\.\w+\/maps/i, /maps\.google/i, /goo\.gl\/maps/i, /maps\.app\.goo\.gl/i];

const MD_IMAGE_RE = /!\[([^\]]*)\]\((https?:\/\/[^\s)]+)\)/gi;
const MD_VIDEO_RE = /\[Video:\s*([^\]]+)\]\((https?:\/\/[^\s)]+)\)/gi;
const MD_DOC_RE = /\[Download\s+([^\]]+)\]\((https?:\/\/[^\s)]+)\)/gi;

const TAG_LINK_RE = /\[link\]\[(.*?)\]\[(.*?)\]/gi;
const BUTTONS_BLOCK_RE = /(?:^|\n)\*\*(.+?)\*\*\s*\n\s*Options:\s*([^\n]+)/i;
const LOCATION_LINE_RE = /(?:^|\n)(?:📍\s*)?Location:\s*(.+?)\s*\((-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\)\s*(?=\n|$)/gi;

type MediaType = "image" | "video" | "document" | "location" | "link";

function classifyUrl(url: string): MediaType {
  if (IMAGE_EXTS.test(url)) return "image";
  if (VIDEO_EXTS.test(url)) return "video";
  if (DOC_EXTS.test(url)) return "document";
  if (MAPS_PATTERNS.some((p) => p.test(url))) return "location";
  return "link";
}

function getFileName(url: string): string {
  try {
    const pathname = new URL(url).pathname;
    const parts = pathname.split("/");
    return decodeURIComponent(parts[parts.length - 1] || url);
  } catch {
    return url;
  }
}

function getMapEmbedUrl(url: string): string {
  return `https://maps.google.com/maps?q=${encodeURIComponent(url)}&output=embed`;
}

function InlineLink({ href, label }: { href: string; label: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-400 hover:text-blue-300 underline underline-offset-2 decoration-blue-400/30 hover:decoration-blue-300/50 transition-colors break-all"
    >
      {label}
    </a>
  );
}

function renderInlineText(content: string) {
  const nodes: ReactNode[] = [];
  const INLINE_LINK_RE = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|https?:\/\/[^\s<>"{}|\\^`[\]]+/gi;
  let cursor = 0;
  let match: RegExpExecArray | null = null;

  while ((match = INLINE_LINK_RE.exec(content)) !== null) {
    const full = match[0];
    const label = match[1];
    const href = match[2] || full;

    if (match.index > cursor) {
      nodes.push(content.slice(cursor, match.index));
    }

    nodes.push(<InlineLink key={`${href}-${match.index}`} href={href} label={label || href} />);
    cursor = match.index + full.length;
  }

  if (cursor < content.length) {
    nodes.push(content.slice(cursor));
  }

  return nodes;
}

function ImagePreview({ url }: { url: string }) {
  const [error, setError] = useState(false);
  const [expanded, setExpanded] = useState(false);

  if (error) {
    return (
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1 mt-1 text-xs text-blue-400 hover:text-blue-300"
      >
        <ImageIcon className="w-3 h-3" />
        Open image
        <ExternalLink className="w-3 h-3" />
      </a>
    );
  }

  return (
    <div className="mt-2">
      <img
        src={url}
        alt="Image"
        onError={() => setError(true)}
        onClick={() => setExpanded((v) => !v)}
        className={`rounded-lg border border-neutral-700 cursor-pointer transition-all hover:opacity-90 ${expanded ? "max-w-full" : "max-w-[320px] max-h-[240px]"} object-cover`}
      />
    </div>
  );
}

function VideoPreview({ url }: { url: string }) {
  return (
    <div className="mt-2">
      <video src={url} controls preload="metadata" className="rounded-lg border border-neutral-700 max-w-[400px] max-h-[300px]" />
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1 mt-1 text-xs text-neutral-500 hover:text-blue-400"
      >
        <Film className="w-3 h-3" />
        Open video
        <ExternalLink className="w-3 h-3" />
      </a>
    </div>
  );
}

function DocumentPreview({ url }: { url: string }) {
  const filename = getFileName(url);
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="mt-2 flex items-center gap-3 p-3 rounded-lg bg-neutral-900/60 border border-neutral-700 hover:border-neutral-500 transition-all max-w-[340px] group"
    >
      <FileText className="w-8 h-8 text-neutral-400 group-hover:text-blue-400 transition-colors" />
      <div className="flex-1 min-w-0">
        <p className="text-sm text-neutral-200 truncate group-hover:text-white transition-colors">{filename}</p>
        <p className="text-[10px] text-neutral-500">Document</p>
      </div>
      <Download className="w-4 h-4 text-neutral-500 group-hover:text-blue-400 transition-colors flex-shrink-0" />
    </a>
  );
}

function LocationPreview({ latitude, longitude, name, address }: { latitude: number; longitude: number; name: string; address: string }) {
  const mapUrl = `https://maps.google.com/maps?q=${encodeURIComponent(`${latitude},${longitude}`)}`;
  const embedUrl = getMapEmbedUrl(`${latitude},${longitude}`);

  return (
    <div className="mt-2">
      <div className="rounded-lg overflow-hidden border border-neutral-700 max-w-[400px]">
        <iframe
          src={embedUrl}
          width="400"
          height="240"
          style={{ border: 0 }}
          loading="lazy"
          referrerPolicy="no-referrer-when-downgrade"
          className="w-full"
        />
      </div>
      <a
        href={mapUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1 mt-1 text-xs text-neutral-500 hover:text-blue-400"
      >
        <MapPin className="w-3 h-3" />
        {name || "Open location"}
        {address ? ` - ${address}` : ""}
      </a>
    </div>
  );
}

function MapLinkPreview({ url }: { url: string }) {
  const embedUrl = getMapEmbedUrl(url);
  return (
    <div className="mt-2">
      <div className="rounded-lg overflow-hidden border border-neutral-700 max-w-[400px]">
        <iframe
          src={embedUrl}
          width="400"
          height="240"
          style={{ border: 0 }}
          loading="lazy"
          referrerPolicy="no-referrer-when-downgrade"
          className="w-full"
        />
      </div>
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1 mt-1 text-xs text-neutral-500 hover:text-blue-400"
      >
        <MapPin className="w-3 h-3" />
        Open in Maps
      </a>
    </div>
  );
}

interface MessageContentProps {
  content: string;
  className?: string;
  onSuggestionClick?: (value: string) => void;
}

export function MessageContent({ content, className = "", onSuggestionClick }: MessageContentProps) {
  const parsed = useMemo(() => {
    let working = (content || "").replace(TAG_LINK_RE, (_m, url, text) => `[${text}](${url})`);

    let buttonTitle = "";
    let buttonOptions: string[] = [];

    const markdownImages: string[] = [];
    const markdownVideos: string[] = [];
    const markdownDocs: string[] = [];
    const locations: Array<{ name: string; address: string; latitude: number; longitude: number }> = [];

    const btnMatch = working.match(BUTTONS_BLOCK_RE);
    if (btnMatch) {
      buttonTitle = btnMatch[1].trim();
      buttonOptions = btnMatch[2].split("|").map((x) => x.trim()).filter(Boolean);
      working = working.replace(btnMatch[0], "").trim();
    }

    working = working.replace(MD_IMAGE_RE, (_m, _alt, url) => {
      markdownImages.push(url.trim());
      return "";
    });

    working = working.replace(MD_VIDEO_RE, (_m, _name, url) => {
      markdownVideos.push(url.trim());
      return "";
    });

    working = working.replace(MD_DOC_RE, (_m, _name, url) => {
      markdownDocs.push(url.trim());
      return "";
    });

    working = working.replace(LOCATION_LINE_RE, (_m, label, lat, lng) => {
      const combined = String(label || "").trim();
      const [namePart, ...rest] = combined.split(",");
      locations.push({
        name: (namePart || "Location").trim(),
        address: rest.join(",").trim() || combined,
        latitude: Number(lat),
        longitude: Number(lng),
      });
      return "\n";
    });

    const cleanedText = working.replace(/\n{3,}/g, "\n\n").trim();

    const directMediaUrls = [...new Set((cleanedText.match(URL_REGEX) || []).filter((u) => classifyUrl(u) !== "link"))];

    return {
      cleanedText,
      markdownImages,
      markdownVideos,
      markdownDocs,
      locations,
      buttonTitle,
      buttonOptions,
      directMediaUrls,
    };
  }, [content]);

  return (
    <div className={`text-sm ${className}`}>
      {parsed.cleanedText && <p className="whitespace-pre-wrap">{renderInlineText(parsed.cleanedText)}</p>}

      {parsed.buttonOptions.length > 0 && (
        <div className="mt-3 p-3 rounded-lg border border-neutral-700 bg-neutral-900/50">
          {parsed.buttonTitle && <p className="text-xs text-neutral-300 mb-2">{parsed.buttonTitle}</p>}
          <div className="flex flex-wrap gap-2">
            {parsed.buttonOptions.map((opt) => (
              <button
                key={opt}
                type="button"
                disabled
                aria-label={`Suggestion option: ${opt}`}
                title={onSuggestionClick ? "Buttons are preview-only in admin chat" : "Buttons are preview-only"}
                className="px-3 py-1.5 rounded-full border border-neutral-700 text-xs text-neutral-400 bg-neutral-900/60 cursor-not-allowed opacity-80"
              >
                {opt}
              </button>
            ))}
          </div>
        </div>
      )}

      {parsed.locations.map((loc, i) => (
        <LocationPreview
          key={`loc-${i}`}
          latitude={loc.latitude}
          longitude={loc.longitude}
          name={loc.name}
          address={loc.address}
        />
      ))}

      {parsed.markdownImages.map((url, i) => (
        <ImagePreview key={`md-img-${i}`} url={url} />
      ))}

      {parsed.markdownVideos.map((url, i) => (
        <VideoPreview key={`md-vid-${i}`} url={url} />
      ))}

      {parsed.markdownDocs.map((url, i) => (
        <DocumentPreview key={`md-doc-${i}`} url={url} />
      ))}

      {parsed.directMediaUrls.map((url, i) => {
        const type = classifyUrl(url);
        if (type === "image") return <ImagePreview key={`url-img-${i}`} url={url} />;
        if (type === "video") return <VideoPreview key={`url-vid-${i}`} url={url} />;
        if (type === "document") return <DocumentPreview key={`url-doc-${i}`} url={url} />;
        if (type === "location") return <MapLinkPreview key={`url-loc-${i}`} url={url} />;
        return null;
      })}
    </div>
  );
}
