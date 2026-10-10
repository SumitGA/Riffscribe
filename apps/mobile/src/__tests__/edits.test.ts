import { type Edit, noteName, positionsFor, upsertEdit } from '@/score/edits';

describe('positionsFor', () => {
  it('lists every string that can play a pitch, string 1 = highest', () => {
    expect(positionsFor(64)).toEqual([
      { string: 1, fret: 0 },
      { string: 2, fret: 5 },
      { string: 3, fret: 9 },
      { string: 4, fret: 14 },
      { string: 5, fret: 19 },
      { string: 6, fret: 24 },
    ]);
  });

  it('counts frets from the capo and knows drop D', () => {
    expect(positionsFor(42, 'standard', 2)).toEqual([{ string: 6, fret: 0 }]);
    expect(positionsFor(38, 'drop_d')).toEqual([{ string: 6, fret: 0 }]);
    expect(positionsFor(38, 'standard')).toEqual([]);
  });
});

describe('noteName', () => {
  it('names MIDI pitches with their octave', () => {
    expect([noteName(64), noteName(60), noteName(51)]).toEqual(['E4', 'C4', 'D#3']);
  });
});

describe('upsertEdit', () => {
  const note = { onset_beats: '1/2', pitch: 64 };
  it('keeps one change per note: the latest', () => {
    let edits: Edit[] = [];
    edits = upsertEdit(edits, { op: 'set_position', note, string: 2, fret: 5 });
    edits = upsertEdit(edits, { op: 'delete', note: { onset_beats: '1', pitch: 60 } });
    edits = upsertEdit(edits, { op: 'set_pitch', note, pitch: 65, string: 1 });

    expect(edits).toEqual([
      { op: 'delete', note: { onset_beats: '1', pitch: 60 } },
      { op: 'set_pitch', note, pitch: 65, string: 1 },
    ]);
  });

  it('always adds new notes', () => {
    const add: Edit = { op: 'add', onset_beats: '2', duration_beats: '1', pitch: 67 };
    expect(upsertEdit(upsertEdit([], add), add)).toHaveLength(2);
  });
});
