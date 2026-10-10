import createClient from 'openapi-fetch';

import type { components, paths } from './schema';

// Types generated from the API's OpenAPI schema (`make api-types`); never edit schema.d.ts.
type Schemas = components['schemas'];
export type CreateJobRequest = Schemas['CreateJobRequest'];
export type CreateJobResponse = Schemas['CreateJobResponse'];
export type Instrument = Schemas['Instrument'];
export type Job = Schemas['JobOut'];
export type JobList = Schemas['JobList'];
export type JobStatus = Schemas['JobStatus'];
export type JobSummary = Schemas['JobSummary'];
export type Me = Schemas['MeOut'];
export type PresignedRequest = Schemas['PresignedRequestOut'];
export type Tuning = Schemas['Tuning'];
export type ScoreVersion = Schemas['VersionOut'];
export type CreateVersionRequest = Schemas['CreateVersionRequest'];

/** A non-2xx answer from the API. `message` is FastAPI's `detail`, readable enough to show. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

// FastAPI errors are {"detail": "..."}, or for request validation {"detail": [{"msg": ...}]}.
function errorMessage(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | undefined)?.detail;
  if (typeof detail === 'string') {
    return detail;
  }
  if (Array.isArray(detail)) {
    const first = detail[0] as { msg?: unknown } | undefined;
    if (typeof first?.msg === 'string') {
      return first.msg;
    }
  }
  return `request failed (HTTP ${status})`;
}

async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await call;
  if (!response.ok || data === undefined) {
    throw new ApiError(response.status, errorMessage(response.status, error));
  }
  return data;
}

function ok({ error, response }: { error?: unknown; response: Response }): void {
  if (!response.ok) {
    throw new ApiError(response.status, errorMessage(response.status, error));
  }
}

export type ApiOptions = {
  baseUrl: string;
  /** The current access token, or null when signed out (requests then go without one). */
  getToken: () => Promise<string | null>;
  fetch?: typeof globalThis.fetch;
};

/** The TabScribe API. Methods resolve with the response body or reject with an ApiError. */
export function createApi({ baseUrl, getToken, fetch }: ApiOptions) {
  const client = createClient<paths>({ baseUrl, fetch });
  client.use({
    async onRequest({ request }) {
      const token = await getToken();
      if (token) {
        request.headers.set('Authorization', `Bearer ${token}`);
      }
      return request;
    },
  });
  const jobPath = (jobId: string) => ({ params: { path: { job_id: jobId } } });

  return {
    me: () => unwrap(client.GET('/me')),
    createJob: (body: CreateJobRequest) => unwrap(client.POST('/jobs', { body })),
    submitJob: (jobId: string) => unwrap(client.POST('/jobs/{job_id}/submit', jobPath(jobId))),
    getJob: (jobId: string) => unwrap(client.GET('/jobs/{job_id}', jobPath(jobId))),
    listJobs: (query: { cursor?: string; limit?: number } = {}) =>
      unwrap(client.GET('/jobs', { params: { query } })),
    // Editor saves (ADR-0011): a new version, rendered by the worker.
    createVersion: (jobId: string, body: CreateVersionRequest) =>
      unwrap(client.POST('/jobs/{job_id}/versions', { ...jobPath(jobId), body })),
    getVersion: (jobId: string, version: number) =>
      unwrap(
        client.GET('/jobs/{job_id}/versions/{number}', {
          params: { path: { job_id: jobId, number: version } },
        }),
      ),
    listVersions: (jobId: string) => unwrap(client.GET('/jobs/{job_id}/versions', jobPath(jobId))),
    // These answer 204 No Content: success has no body to unwrap.
    /** Deletes the account and everything in it (Play / App Store requirement). */
    deleteAccount: async (): Promise<void> => ok(await client.DELETE('/me')),
    deleteJob: async (jobId: string): Promise<void> =>
      ok(await client.DELETE('/jobs/{job_id}', jobPath(jobId))),
    registerPushToken: async (token: string, platform: 'ios' | 'android'): Promise<void> =>
      ok(await client.PUT('/me/push-tokens', { body: { token, platform } })),
    removePushToken: async (token: string): Promise<void> =>
      ok(await client.DELETE('/me/push-tokens/{token}', { params: { path: { token } } })),
  };
}

export type Api = ReturnType<typeof createApi>;
