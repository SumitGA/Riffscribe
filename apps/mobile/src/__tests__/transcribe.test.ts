import type { Api, CreateJobResponse, Job } from '@/api/client';
import type { AudioClip } from '@/audio/clip';
import { type Step, startTranscription, type Uploader } from '@/jobs/transcribe';

jest.mock('expo-file-system', () => ({ File: jest.fn(), UploadType: { BINARY_CONTENT: 0 } }));

const clip: AudioClip = {
  uri: 'file:///cache/take.m4a',
  name: 'take.m4a',
  contentType: 'audio/mp4',
  sizeBytes: 1234,
};
const put = {
  method: 'PUT',
  url: 'https://s3.test/put',
  headers: { 'Content-Type': 'audio/mp4' },
  expires_in_s: 900,
};
const created = { job: { id: 'job-1' }, upload: put } as unknown as CreateJobResponse;
const queued = { id: 'job-1', status: 'queued' } as unknown as Job;

function fakeApi() {
  return {
    createJob: jest.fn(async () => created),
    submitJob: jest.fn(async () => queued),
  } satisfies Pick<Api, 'createJob' | 'submitJob'>;
}

describe('startTranscription', () => {
  it('creates the job, uploads to the presigned URL, then submits', async () => {
    const api = fakeApi();
    const upload = jest.fn<ReturnType<Uploader>, Parameters<Uploader>>(
      async (_uri, _req, onProgress) => {
        onProgress(0.5);
        onProgress(1);
      },
    );
    const steps: Step[] = [];

    await expect(
      startTranscription(api, clip, 'piano', upload, (s) => steps.push(s)),
    ).resolves.toBe(queued);
    expect(api.createJob).toHaveBeenCalledWith({
      instrument: 'piano',
      content_type: 'audio/mp4',
      size_bytes: 1234,
    });
    expect(upload).toHaveBeenCalledWith(clip.uri, put, expect.any(Function));
    expect(api.submitJob).toHaveBeenCalledWith('job-1');
    expect(steps).toEqual([
      { step: 'creating' },
      { step: 'uploading', fraction: 0 },
      { step: 'uploading', fraction: 0.5 },
      { step: 'uploading', fraction: 1 },
      { step: 'submitting' },
    ]);
  });

  it("doesn't submit when the upload fails", async () => {
    const api = fakeApi();
    const upload: Uploader = async () => {
      throw new Error('The upload failed (HTTP 403). Try again.');
    };

    await expect(startTranscription(api, clip, 'guitar', upload)).rejects.toThrow('HTTP 403');
    expect(api.submitJob).not.toHaveBeenCalled();
  });
});
