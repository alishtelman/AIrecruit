"use client";

type PreparedInterviewMedia = {
  webcamStream: MediaStream;
  screenStream: MediaStream | null;
  createdAt: number;
};

type PrepareInterviewMediaOptions = {
  requireCameraAndMic?: boolean;
  tryScreenShare?: boolean;
};

const SESSION_TTL_MS = 2 * 60 * 1000;

let preparedMedia: PreparedInterviewMedia | null = null;

function stopStream(stream: MediaStream | null) {
  if (!stream) return;
  stream.getTracks().forEach((track) => track.stop());
}

export function clearPreparedInterviewMedia() {
  if (!preparedMedia) return;
  stopStream(preparedMedia.screenStream);
  stopStream(preparedMedia.webcamStream);
  preparedMedia = null;
}

export async function prepareInterviewMediaSession(
  options: PrepareInterviewMediaOptions = {},
): Promise<void> {
  const requireCameraAndMic = options.requireCameraAndMic ?? true;
  const tryScreenShare = options.tryScreenShare ?? true;
  clearPreparedInterviewMedia();

  let webcamStream: MediaStream | null = null;
  let screenStream: MediaStream | null = null;

  try {
    if (requireCameraAndMic) {
      webcamStream = await navigator.mediaDevices.getUserMedia({
        video: true,
        audio: true,
      });
    }

    if (!webcamStream) {
      throw new Error("Camera or microphone permission is required.");
    }

    if (tryScreenShare) {
      try {
        screenStream = await navigator.mediaDevices.getDisplayMedia({
          video: { frameRate: { ideal: 15, max: 30 } },
          audio: false,
        });
      } catch {
        screenStream = null;
      }
    }

    preparedMedia = {
      screenStream,
      webcamStream: webcamStream,
      createdAt: Date.now(),
    };
  } catch (error) {
    stopStream(screenStream);
    stopStream(webcamStream);
    throw error;
  }
}

export function consumePreparedInterviewMedia():
  | { screenStream: MediaStream | null; webcamStream: MediaStream }
  | null {
  if (!preparedMedia) {
    return null;
  }
  if (Date.now() - preparedMedia.createdAt > SESSION_TTL_MS) {
    clearPreparedInterviewMedia();
    return null;
  }
  const consumed = {
    screenStream: preparedMedia.screenStream,
    webcamStream: preparedMedia.webcamStream,
  };
  preparedMedia = null;
  return consumed;
}
