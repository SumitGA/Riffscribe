import { Directory, File, Paths } from 'expo-file-system';

import { findTake, forgetTake, keepTake } from '@/audio/takes';

function recording(name = 'take.m4a'): File {
  const dir = new Directory(Paths.cache, 'recordings');
  dir.create({ idempotent: true, intermediates: true });
  const file = new File(dir, name);
  file.write('audio');
  return file;
}

describe('takes', () => {
  it('keeps a copy per job that survives the original', async () => {
    const original = recording();
    await keepTake('job-1', original.uri);
    original.delete();

    const kept = findTake('job-1');
    expect(kept?.name).toBe('job-1.m4a');
    expect(kept?.textSync()).toBe('audio');
    expect(findTake('job-2')).toBeNull();
  });

  it('forgets the copy when the job is deleted', async () => {
    await keepTake('job-3', recording('other.wav').uri);
    expect(findTake('job-3')?.name).toBe('job-3.wav');

    forgetTake('job-3');
    expect(findTake('job-3')).toBeNull();
  });

  it('never fails the transcription when the file is gone', async () => {
    const warn = jest.spyOn(console, 'warn').mockImplementation(() => {});
    await expect(keepTake('job-4', 'file:///mock/cache/missing.m4a')).resolves.toBeUndefined();
    expect(findTake('job-4')).toBeNull();
    warn.mockRestore();
  });
});
