import { File, UploadType } from 'expo-file-system';

import type { Api, CreateJobRequest, Job, PresignedRequest } from '@/api/client';
import type { AudioClip } from '@/audio/clip';

/** Sends a local file to a presigned URL, reporting progress from 0 to 1. */
export type Uploader = (
  uri: string,
  request: PresignedRequest,
  onProgress: (fraction: number) => void,
) => Promise<void>;

/** What the user chose for the take: everything in a new job except the upload's details. */
export type TakeOptions = Omit<CreateJobRequest, 'content_type' | 'size_bytes'>;

export type Step =
  { step: 'creating' } | { step: 'uploading'; fraction: number } | { step: 'submitting' };

/**
 * The job flow from the app's side (CLAUDE.md, steps 1-3): create the job, upload the audio
 * straight to object storage with the presigned PUT (it never passes through the API), then
 * submit it to the queue. Resolves with the queued job.
 */
export async function startTranscription(
  api: Pick<Api, 'createJob' | 'submitJob'>,
  clip: AudioClip,
  options: TakeOptions,
  upload: Uploader,
  onStep: (step: Step) => void = () => {},
): Promise<Job> {
  onStep({ step: 'creating' });
  const created = await api.createJob({
    ...options,
    content_type: clip.contentType,
    size_bytes: clip.sizeBytes,
  });
  onStep({ step: 'uploading', fraction: 0 });
  await upload(clip.uri, created.upload, (fraction) => onStep({ step: 'uploading', fraction }));
  onStep({ step: 'submitting' });
  return api.submitJob(created.job.id);
}

/** The real uploader: the file goes as the raw request body with the presigned headers. */
export const uploadFile: Uploader = async (uri, request, onProgress) => {
  const result = await new File(uri).upload(request.url, {
    httpMethod: request.method as 'PUT',
    uploadType: UploadType.BINARY_CONTENT,
    headers: request.headers,
    onProgress: ({ bytesSent, totalBytes }) => {
      if (totalBytes > 0) {
        onProgress(bytesSent / totalBytes);
      }
    },
  });
  if (result.status < 200 || result.status >= 300) {
    throw new Error(`The upload failed (HTTP ${result.status}). Try again.`);
  }
};
