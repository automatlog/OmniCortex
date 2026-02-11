import { useSocketContext } from "../../SocketContext";

export const Controls = () => {
  const { sendMessage } = useSocketContext();

  const sendControlBOS = () => {
    sendMessage({
      type: "control",
      action: "start",
    });
  };

  const sendControlEOS = () => {
    sendMessage({
      type: "control",
      action: "endTurn",
    });
  };

  return (
    <div className="flex w-full justify-between gap-3">
      <button
        className="flex-grow px-4 py-2 rounded-lg bg-neutral-700 hover:bg-neutral-600 text-white text-sm transition-colors"
        onClick={sendControlEOS}
      >
        End Stream
      </button>
      <button
        className="flex-grow px-4 py-2 rounded-lg bg-neutral-700 hover:bg-neutral-600 text-white text-sm transition-colors"
        onClick={sendControlBOS}
      >
        Begin Stream
      </button>
    </div>
  );
};
