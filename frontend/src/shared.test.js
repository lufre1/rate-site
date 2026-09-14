import {
  toDateKey, parseServerDate, formatRelativeDate, thumbSrc, thumbErrorHandler,
} from './shared';

// These are the two date helpers that had UTC/local bugs. Both are pure, so they
// are testable without rendering anything.

describe('toDateKey', () => {
  test('formats a date as local YYYY-MM-DD', () => {
    // Month is 0-indexed: 8 = September.
    expect(toDateKey(new Date(2026, 8, 1))).toBe('2026-09-01');
  });

  test('zero-pads month and day', () => {
    expect(toDateKey(new Date(2026, 0, 5))).toBe('2026-01-05');
  });

  test('uses the LOCAL calendar day, not the UTC one', () => {
    // The regression: toISOString().slice(0, 10) on this instant yields
    // 2026-08-31 in any timezone east of UTC, so the app opened on the wrong
    // day's menu between midnight and 02:00 Berlin time.
    const justAfterLocalMidnight = new Date(2026, 8, 1, 0, 30);
    expect(toDateKey(justAfterLocalMidnight)).toBe('2026-09-01');
  });

  test('defaults to now', () => {
    expect(toDateKey()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});

describe('parseServerDate', () => {
  test('reads an offset-less timestamp as UTC, not local', () => {
    // What the API actually sends: datetime.isoformat() on a naive UTC value.
    expect(parseServerDate('2026-09-01T12:00:00').toISOString())
      .toBe('2026-09-01T12:00:00.000Z');
  });

  test('keeps microseconds', () => {
    expect(parseServerDate('2026-09-01T12:00:00.123456').toISOString())
      .toBe('2026-09-01T12:00:00.123Z');
  });

  test('leaves an explicit offset alone', () => {
    expect(parseServerDate('2026-09-01T12:00:00Z').toISOString())
      .toBe('2026-09-01T12:00:00.000Z');
    expect(parseServerDate('2026-09-01T14:00:00+02:00').toISOString())
      .toBe('2026-09-01T12:00:00.000Z');
  });

  test('leaves a date-only string alone (already UTC per spec)', () => {
    expect(parseServerDate('2026-09-01').toISOString())
      .toBe('2026-09-01T00:00:00.000Z');
  });
});

describe('formatRelativeDate', () => {
  // Identity translator: assert on the key and count rather than on German text.
  const t = (key, opts) => (opts ? `${key}:${opts.count}` : key);

  test('an offset-less timestamp minutes old reads as today', () => {
    const now = new Date();
    // Strip the Z the way the backend does, so this is the real input shape.
    const naiveUtc = new Date(now.getTime() - 60_000).toISOString().replace('Z', '');
    expect(formatRelativeDate(naiveUtc, t)).toBe('dates.today');
  });

  test('counts whole days back', () => {
    const threeDaysAgo = new Date(Date.now() - 3 * 86400000).toISOString().replace('Z', '');
    expect(formatRelativeDate(threeDaysAgo, t)).toBe('dates.daysAgo:3');
  });
});

// Uploads are stored twice -- the display copy under its own name and a 240px
// version under /uploads/thumbs/ -- and the pairing is derived, not stored, so
// this is the only thing keeping the two halves in agreement.
describe('thumbSrc', () => {
  test('points an upload path at its thumbnail', () => {
    expect(thumbSrc('/uploads/abc123.jpg')).toBe('/uploads/thumbs/abc123.jpg');
  });

  test('leaves a non-upload path alone', () => {
    expect(thumbSrc('/static/media/logo.png')).toBe('/static/media/logo.png');
  });

  test('passes null and undefined through', () => {
    // Reviews without a photo carry photo_url: null.
    expect(thumbSrc(null)).toBe(null);
    expect(thumbSrc(undefined)).toBe(undefined);
  });

  test('does not rewrite a path that merely contains /uploads/', () => {
    expect(thumbSrc('/api/v1/uploads/x.jpg')).toBe('/api/v1/uploads/x.jpg');
  });
});

describe('thumbErrorHandler', () => {
  const makeImg = () => ({ dataset: {}, style: {}, src: '/uploads/thumbs/a.jpg' });

  test('falls back to the full photo the first time', () => {
    // Uploads from before the backfill, and anything render_upload() could not
    // decode, have no thumbnail.
    const target = makeImg();
    thumbErrorHandler('/uploads/a.jpg')({ target });
    expect(target.src).toBe('/uploads/a.jpg');
    expect(target.style.display).toBeUndefined();
  });

  test('hides the image if the full photo fails too', () => {
    const target = makeImg();
    const onError = thumbErrorHandler('/uploads/a.jpg');
    onError({ target });
    onError({ target });
    expect(target.style.display).toBe('none');
  });
});
