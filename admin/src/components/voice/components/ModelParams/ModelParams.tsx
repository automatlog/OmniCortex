import { FC, RefObject, useState } from "react";
import { useModelParams } from "../../hooks/useModelParams";

type ModelParamsProps = {
  isConnected: boolean;
  modal?: RefObject<HTMLDialogElement>;
} & ReturnType<typeof useModelParams>;

export const ModelParams: FC<ModelParamsProps> = ({
  textTemperature,
  textTopk,
  audioTemperature,
  audioTopk,
  padMult,
  repetitionPenalty,
  repetitionPenaltyContext,
  setParams,
  resetParams,
  isConnected,
  textPrompt,
  voicePrompt,
  randomSeed,
  modal,
}) => {
  const [modalVoicePrompt, setModalVoicePrompt] = useState<string>(voicePrompt);
  const [modalTextPrompt, setModalTextPrompt] = useState<string>(textPrompt);

  return (
    <div className="p-2 mt-6 self-center flex flex-col items-center text-center">
      <table>
        <tbody>
          <tr>
            <td className="text-sm text-neutral-400 pr-2">Text Prompt:</td>
            <td className="w-12 text-center text-sm">{modalTextPrompt}</td>
            <td className="p-2">
              <input
                className="bg-neutral-800 text-white border border-neutral-600 rounded px-2 py-1 text-sm"
                disabled={isConnected}
                type="text"
                value={modalTextPrompt}
                onChange={(e) => setModalTextPrompt(e.target.value)}
              />
            </td>
          </tr>
          <tr>
            <td className="text-sm text-neutral-400 pr-2">Voice Prompt:</td>
            <td className="w-12 text-center text-sm">{modalVoicePrompt}</td>
            <td className="p-2">
              <select
                className="bg-neutral-800 text-white border border-neutral-600 rounded px-2 py-1 text-sm"
                disabled={isConnected}
                value={modalVoicePrompt}
                onChange={(e) => setModalVoicePrompt(e.target.value)}
              >
                <option value="NATF0.pt">NATF0.pt</option>
                <option value="NATF1.pt">NATF1.pt</option>
                <option value="NATF2.pt">NATF2.pt</option>
                <option value="NATF3.pt">NATF3.pt</option>
                <option value="NATM0.pt">NATM0.pt</option>
                <option value="NATM1.pt">NATM1.pt</option>
                <option value="NATM2.pt">NATM2.pt</option>
                <option value="NATM3.pt">NATM3.pt</option>
                <option value="VARF0.pt">VARF0.pt</option>
                <option value="VARF1.pt">VARF1.pt</option>
                <option value="VARF2.pt">VARF2.pt</option>
                <option value="VARF3.pt">VARF3.pt</option>
                <option value="VARF4.pt">VARF4.pt</option>
                <option value="VARM0.pt">VARM0.pt</option>
                <option value="VARM1.pt">VARM1.pt</option>
                <option value="VARM2.pt">VARM2.pt</option>
                <option value="VARM3.pt">VARM3.pt</option>
                <option value="VARM4.pt">VARM4.pt</option>
              </select>
            </td>
          </tr>
        </tbody>
      </table>
      <div>
        <button
          onClick={resetParams}
          className="m-2 px-4 py-2 rounded-lg bg-neutral-700 hover:bg-neutral-600 text-white text-sm transition-colors"
        >
          Reset
        </button>
        <button
          onClick={() => {
            setParams({
              textTemperature,
              textTopk,
              audioTemperature,
              audioTopk,
              padMult,
              repetitionPenalty,
              repetitionPenaltyContext,
              textPrompt: modalTextPrompt,
              voicePrompt: modalVoicePrompt,
              randomSeed,
            });
            modal?.current?.close();
          }}
          className="m-2 px-4 py-2 rounded-lg bg-green-600 hover:bg-green-500 text-white text-sm transition-colors"
        >
          Validate
        </button>
      </div>
    </div>
  );
};
