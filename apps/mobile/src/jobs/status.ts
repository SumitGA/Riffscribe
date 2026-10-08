import type { Job, JobStatus } from '@/api/client';

/** The pipeline's stages in order (tabscribe_platform.jobqueue.STAGES), in words a player knows. */
export const STAGES: { stage: string; label: string }[] = [
  { stage: 'normalize', label: 'Preparing the audio' },
  { stage: 'separate', label: 'Isolating the instrument' },
  { stage: 'transcribe', label: 'Listening for notes' },
  { stage: 'quantize', label: 'Finding the beat' },
  { stage: 'notation', label: 'Writing the sheet music' },
  { stage: 'tab', label: 'Working out the fingering' },
];

export const STATUS_LABELS: Record<JobStatus, string> = {
  pending_upload: 'Waiting for the upload',
  queued: 'Queued',
  running: 'Transcribing',
  succeeded: 'Ready',
  failed: 'Failed',
};

export type StageState = 'waiting' | 'running' | 'done' | 'skipped' | 'failed';

export function isFinished(status: JobStatus): boolean {
  return status === 'succeeded' || status === 'failed';
}

/** Every stage with its state; stages the worker hasn't reached yet are `waiting`. */
export function stageStates(
  job: Pick<Job, 'stages'>,
): { label: string; state: StageState; seconds?: number }[] {
  return STAGES.map(({ stage, label }) => {
    const run = job.stages.find((s) => s.stage === stage);
    if (!run) {
      return { label, state: 'waiting' as const };
    }
    const state: StageState =
      run.status === 'succeeded' || run.status === 'cached'
        ? 'done'
        : run.status === 'queued'
          ? 'waiting'
          : run.status;
    const seconds =
      run.started_at && run.finished_at
        ? (Date.parse(run.finished_at) - Date.parse(run.started_at)) / 1000
        : undefined;
    return { label, state, seconds };
  });
}

/** "8 Oct, 13:22" in the phone's locale. */
export function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}
