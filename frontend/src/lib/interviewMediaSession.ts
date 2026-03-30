"use client";

type PreparedInterviewMedia = {
  screenStream: MediaStream;
  webcamStream: MediaStream;
  createdAt: number;
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

export async function prepareInterviewMediaSession(): Promise<void> {
  clearPreparedInterviewMedia();

  const screenStream = await navigator.mediaDevices.getDisplayMedia({
    video: { frameRate: { ideal: 15, max: 30 } },
    audio: false,
  });

  try {
    const webcamStream = await navigator.mediaDevices.getUserMedia({
      video: true,
      audio: true,
    });

    preparedMedia = {
      screenStream,
      webcamStream,
      createdAt: Date.now(),
    };
  } catch (error) {
    stopStream(screenStream);
    throw error;
  }
}

export function consumePreparedInterviewMedia():
  | { screenStream: MediaStream; webcamStream: MediaStream }
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
