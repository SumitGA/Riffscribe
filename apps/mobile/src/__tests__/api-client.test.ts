import { ApiError, createApi } from '@/api/client';

const BASE = 'http://api.test';

// A fetch that records requests and answers each with the next queued response.
function fakeFetch(...responses: Response[]) {
  const requests: Request[] = [];
  const fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    requests.push(new Request(input, init));
    const response = responses.shift();
    if (!response) {
      throw new Error('unexpected request');
    }
    return response;
  });
  return { fetch: fetch as unknown as typeof globalThis.fetch, requests };
}

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

const me = { user_id: 'alice', jobs_this_month: 1, jobs_per_month: 10 };

describe('createApi', () => {
  it('sends the bearer token and returns the body', async () => {
    const { fetch, requests } = fakeFetch(json(200, me));
    const api = createApi({ baseUrl: BASE, getToken: async () => 'tok', fetch });

    await expect(api.me()).resolves.toEqual(me);
    expect(requests[0]?.url).toBe(`${BASE}/me`);
    expect(requests[0]?.headers.get('Authorization')).toBe('Bearer tok');
  });

  it('sends no Authorization header when signed out', async () => {
    const { fetch, requests } = fakeFetch(json(200, me));
    const api = createApi({ baseUrl: BASE, getToken: async () => null, fetch });

    await api.me();
    expect(requests[0]?.headers.has('Authorization')).toBe(false);
  });

  it('posts a new job as JSON', async () => {
    const { fetch, requests } = fakeFetch(json(201, { job: {}, upload: {} }));
    const api = createApi({ baseUrl: BASE, getToken: async () => 'tok', fetch });

    await api.createJob({ instrument: 'guitar', content_type: 'audio/mp4', size_bytes: 1234 });
    expect(requests[0]?.method).toBe('POST');
    expect(requests[0]?.url).toBe(`${BASE}/jobs`);
    await expect(requests[0]?.json()).resolves.toEqual({
      instrument: 'guitar',
      content_type: 'audio/mp4',
      size_bytes: 1234,
    });
  });

  it('fills in path and query parameters', async () => {
    const { fetch, requests } = fakeFetch(
      json(200, {}),
      json(200, {}),
      json(200, { jobs: [], next_cursor: null }),
    );
    const api = createApi({ baseUrl: BASE, getToken: async () => 'tok', fetch });

    await api.submitJob('j1');
    await api.getJob('j1');
    await api.listJobs({ cursor: 'abc', limit: 5 });
    expect(requests.map((r) => `${r.method} ${r.url}`)).toEqual([
      `POST ${BASE}/jobs/j1/submit`,
      `GET ${BASE}/jobs/j1`,
      `GET ${BASE}/jobs?cursor=abc&limit=5`,
    ]);
  });

  it('deletes a job (204, no body)', async () => {
    const { fetch, requests } = fakeFetch(
      new Response(null, { status: 204 }),
      json(404, { detail: 'job not found' }),
    );
    const api = createApi({ baseUrl: BASE, getToken: async () => 'tok', fetch });

    await expect(api.deleteJob('j1')).resolves.toBeUndefined();
    expect(`${requests[0]?.method} ${requests[0]?.url}`).toBe(`DELETE ${BASE}/jobs/j1`);
    await expect(api.deleteJob('j1')).rejects.toMatchObject({
      status: 404,
      message: 'job not found',
    });
  });

  it("rejects with an ApiError carrying FastAPI's detail", async () => {
    const { fetch } = fakeFetch(json(429, { detail: 'monthly limit of 10 jobs reached' }));
    const api = createApi({ baseUrl: BASE, getToken: async () => 'tok', fetch });

    const error = await api.submitJob('j1').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 429, message: 'monthly limit of 10 jobs reached' });
  });

  it('uses the first message of a validation error', async () => {
    const { fetch } = fakeFetch(json(422, { detail: [{ loc: ['body'], msg: 'Field required' }] }));
    const api = createApi({ baseUrl: BASE, getToken: async () => 'tok', fetch });

    await expect(api.getJob('j1')).rejects.toMatchObject({
      status: 422,
      message: 'Field required',
    });
  });

  it('falls back to the status when the error has no detail', async () => {
    const { fetch } = fakeFetch(new Response('Bad Gateway', { status: 502 }));
    const api = createApi({ baseUrl: BASE, getToken: async () => 'tok', fetch });

    await expect(api.me()).rejects.toMatchObject({
      status: 502,
      message: 'request failed (HTTP 502)',
    });
  });
});
