const fs = require('fs');
const html = fs.readFileSync('index.html', 'utf8');
const m = html.match(/<script type="module">([\s\S]*?)<\/script>/);
try { new Function(m[1].replace(/^import.*$/gm, '// $&')); console.log('✓ Embedded parses'); } catch (e) { console.log('✗', e.message); process.exit(1); }
const checks = [
  ['Spotlight fix (inside room)',   'x + normal * 1.1, WALL_H - 0.3'],
  ['AmbientLight 0.75',              'AmbientLight(0xfff1d8, 0.75)'],
  ['DirectionalLight sun',           'DirectionalLight(0xfff1d8, 0.45)'],
  ['Exposure 1.5',                    'toneMappingExposure = 1.5'],
  ['Canvas emissive 0.45',           'emissive: 0xffffff, emissiveIntensity: 0.45'],
  ['Canvas emissiveMap applied',     'canvasMat.emissiveMap = tex'],
  ['Flag emissive 1.0',              'emissiveMap: flagTex, emissiveIntensity: 1.0'],
  ['Flag size 2.4x1.2',              'const flagW = 2.4, flagH = 1.2'],
  ['Country sign emissive 2.2',      'emissiveMap: nameTex, emissiveIntensity: 2.2'],
  ['Dust motes removed',             'Dust motes removed'],
  ['Joystick avocado SVG',           'class="avocado" viewBox'],
  ['Avocado bob animation',          'avocadoBob'],
  ['Mobile touch IDs separated',     'let joyTouchId = null, lookTouchId = null'],
  ['Pitch sensitivity lowered',      'LOOK_SENS_Y = 0.0022'],
  ['Foyer arch header engraved',     'A  MUSEUM  OF  US  ·  EST.  2024'],
  ['Foyer floor medallion',          'EST.  MMXXIV'],
  ['Wainscoting chair rail',         'classic wainscoting divider'],
  ['Roman numeral helper',           'const toRoman = (n) =>'],
  ['PHOTO_DATA embedded',            'window.PHOTO_DATA'],
];
let pass = 0, fail = 0;
checks.forEach(([label, str]) => {
  if (html.includes(str)) { console.log('✓', label); pass++; }
  else { console.log('✗', label, ' -- NOT FOUND'); fail++; }
});
console.log(`\n${pass}/${pass+fail} checks passed — ${(html.length/1024/1024).toFixed(2)} MB`);
