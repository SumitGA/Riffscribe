import { File } from 'expo-file-system';
import { printToFileAsync } from 'expo-print';
import { shareAsync } from 'expo-sharing';

import { fileName, shareBase64, shareDownload, sharePdf } from '@/score/exports';

jest.mock('expo-sharing', () => ({ shareAsync: jest.fn(async () => {}) }));
jest.mock('expo-print', () => ({
  printToFileAsync: jest.fn(async () => ({ uri: 'file:///cache/print.pdf' })),
}));
jest.mock('expo-file-system', () => {
  class MockFile {
    static downloadFileAsync = jest.fn(async (_url: string, to: MockFile) => to);
    static written = new Map<string, Uint8Array>();
    static moved: [string, string][] = [];
    uri: string;
    exists = false;
    constructor(...parts: (string | { uri: string })[]) {
      this.uri = parts.map((p) => (typeof p === 'string' ? p : p.uri)).join('/');
    }
    write(bytes: Uint8Array) {
      MockFile.written.set(this.uri, bytes);
    }
    delete() {}
    async move(to: MockFile) {
      MockFile.moved.push([this.uri, to.uri]);
    }
  }
  class MockDirectory extends MockFile {
    create() {}
  }
  return { File: MockFile, Directory: MockDirectory, Paths: { cache: { uri: 'file:///cache' } } };
});

type MockFileClass = typeof File & {
  downloadFileAsync: jest.Mock;
  written: Map<string, Uint8Array>;
  moved: [string, string][];
};
const MockFile = File as unknown as MockFileClass;

describe('fileName', () => {
  it('keeps a readable, safe name with the right extension', () => {
    expect(fileName('Blues riff: take #2!', 'midi')).toBe('Blues riff take 2.mid');
    expect(fileName('Für Elise', 'pdf')).toBe('Für Elise.pdf');
    expect(fileName('  ', 'guitarPro')).toBe('Riffscribe score.gp');
    expect(fileName('../../etc/passwd', 'musicxml')).toBe('.. .. etc passwd.musicxml');
  });
});

describe('sharing', () => {
  it('downloads a presigned file and shares it', async () => {
    const request = { method: 'GET', url: 'https://s3/score', headers: {}, expires_in_s: 900 };
    await shareDownload(request, 'Riff.musicxml', 'musicxml');
    expect(MockFile.downloadFileAsync).toHaveBeenCalledWith(
      'https://s3/score',
      expect.objectContaining({ uri: 'file:///cache/exports/Riff.musicxml' }),
      { headers: {} },
    );
    expect(shareAsync).toHaveBeenLastCalledWith('file:///cache/exports/Riff.musicxml', {
      mimeType: 'application/vnd.recordare.musicxml+xml',
      UTI: 'public.xml',
      dialogTitle: 'Share MusicXML',
    });
  });

  it('writes base64 data from the score page as bytes', async () => {
    await shareBase64(btoa('PK\u0003\u0004'), 'Riff.gp', 'guitarPro');
    expect(Array.from(MockFile.written.get('file:///cache/exports/Riff.gp') ?? [])).toEqual([
      0x50, 0x4b, 3, 4,
    ]);
    expect(shareAsync).toHaveBeenLastCalledWith(
      'file:///cache/exports/Riff.gp',
      expect.objectContaining({ dialogTitle: 'Share Guitar Pro' }),
    );
  });

  it('prints HTML to an A4 PDF under the score name', async () => {
    await sharePdf('<html></html>', 'Riff.pdf');
    expect(printToFileAsync).toHaveBeenCalledWith({
      html: '<html></html>',
      width: 595,
      height: 842,
    });
    expect(MockFile.moved).toContainEqual([
      'file:///cache/print.pdf',
      'file:///cache/exports/Riff.pdf',
    ]);
    expect(shareAsync).toHaveBeenLastCalledWith(
      'file:///cache/exports/Riff.pdf',
      expect.objectContaining({ mimeType: 'application/pdf' }),
    );
  });
});
