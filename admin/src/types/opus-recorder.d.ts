declare module "opus-recorder" {
  export interface RecorderOptions {
    mediaTrackConstraints?: MediaStreamConstraints | MediaTrackConstraints;
    encoderPath?: string;
    bufferLength?: number;
    encoderFrameSize?: number;
    encoderSampleRate?: number;
    maxFramesPerPage?: number;
    numberOfChannels?: number;
    recordingGain?: number;
    resampleQuality?: number;
    encoderComplexity?: number;
    encoderApplication?: number;
    streamPages?: boolean;
    [key: string]: unknown;
  }

  export default class Recorder {
    constructor(options?: RecorderOptions);
    encodedSamplePosition: number;
    ondataavailable: ((data: Uint8Array) => void) | null;
    onstart: (() => void) | null;
    onstop: (() => void) | null;
    start(): void;
    stop(): void;
  }
}
