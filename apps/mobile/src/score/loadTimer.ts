/**
 * Where the wait between opening a score and Play becoming available goes: milliseconds since
 * the score screen opened, per step (docs/performance.md). One score screen is open at a time,
 * so one timer is enough; ScoreView logs the steps once the player is ready.
 */
let startedAt = 0;
let marks: Record<string, number> = {};

export function startScoreTimer(): void {
  startedAt = performance.now();
  marks = {};
}

export function markScore(step: string): void {
  marks[step] = Math.round(performance.now() - startedAt);
}

export function scoreMarks(): Record<string, number> {
  return { ...marks };
}
