const de = require('./de.json');
const en = require('./en.json');

function keyPaths(obj, prefix = '') {
  return Object.entries(obj).flatMap(([k, v]) =>
    v && typeof v === 'object'
      ? keyPaths(v, prefix + k + '.')
      : [prefix + k]
  );
}

const get = (obj, path) => path.split('.').reduce((acc, k) => acc[k], obj);

test('de and en have identical key structure', () => {
  expect(keyPaths(de).sort()).toEqual(keyPaths(en).sort());
});

test('German UI strings are actually translated (differ from English)', () => {
  const samples = ['ui.rate', 'ui.reviews', 'ui.allMensas', 'mealTypes.main', 'dates.today'];
  for (const path of samples) {
    expect(get(de, path)).not.toBe(get(en, path));
  }
});

test('no single-brace interpolation placeholders remain', () => {
  const combined = JSON.stringify(de) + JSON.stringify(en);
  // Matches {word} but NOT {{word}} (i18next's required syntax).
  const bad = combined.match(/(?<!\{)\{[a-zA-Z]\w*\}(?!\})/g);
  expect(bad).toBeNull();
});
