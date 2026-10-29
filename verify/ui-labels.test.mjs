/* UI axis labels must never read "undefined", at any canvas width.
 *
 * History: the Panel C compass used `compass[(a / 90) % 4]`, which returned
 * undefined for the intercardinal azimuths (45/135/225/315), and both axis
 * renders produced overlapping labels on phone-sized canvases. The helpers
 * below live next to the drawing code so the string the test asserts is the
 * exact string the canvas draws — not a reimplementation.
 *
 *   node verify/ui-labels.test.mjs
 */
import { azLabel, azStepFor } from "../app/src/panorama.js";
import { monthStepFor } from "../app/src/timeline.js";

let passed = 0;
let failed = 0;

function check(name, ok, detail = "") {
  if (ok) {
    passed += 1;
    console.log(`  [PASS] ${name}  ${detail}`);
  } else {
    failed += 1;
    console.error(`  [FAIL] ${name}  ${detail}`);
  }
}

/* --- compass: every 45-degree tick has a real label, none say undefined --- */
const expected = {
  0: "N 0°", 45: "NE 45°", 90: "E 90°", 135: "SE 135°",
  180: "S 180°", 225: "SW 225°", 270: "W 270°", 315: "NW 315°",
  360: "N 360°",
};
for (const [deg, want] of Object.entries(expected)) {
  const got = azLabel(Number(deg));
  check(`azLabel(${deg}) is a real point of the compass`, got === want, got);
  check(`azLabel(${deg}) never prints "undefined"`, !got.includes("undefined"));
}

/* --- narrow panels (phone) drop to the four cardinal points --- */
check("azStepFor(390) = 90 (phone)", azStepFor(390) === 90, String(azStepFor(390)));
check("azStepFor(500) = 90 (small tablet)", azStepFor(500) === 90, String(azStepFor(500)));
check("azStepFor(1280) = 45 (desktop)", azStepFor(1280) === 45, String(azStepFor(1280)));

for (const width of [390, 500, 1280]) {
  const step = azStepFor(width);
  const gap = Math.trunc((width - 44 - 74) / (360 / step));
  check(`azStepFor(${width}) labels have room`, gap >= 60,
    `${(width - 44 - 74) / (360 / step) | 0} px per label`);
}

/* --- timeline months thin on narrow canvases --- */
check("monthStepFor(390) = 3", monthStepFor(390) === 3, String(monthStepFor(390)));
check("monthStepFor(640) = 2", monthStepFor(640) === 2, String(monthStepFor(640)));
check("monthStepFor(1280) = 1", monthStepFor(1280) === 1, String(monthStepFor(1280)));

for (const width of [390, 640, 1280]) {
  const step = monthStepFor(width);
  const labels = Math.floor(13 / step);
  const gap = Math.trunc((width - 44 - 12) / labels);
  check(`monthStepFor(${width}) labels have room`, gap >= 55,
    `${labels} labels, ~${gap} px`);
}

console.log(failed === 0
  ? `\nUI label regression: ${passed} passed, 0 failed.`
  : `\nUI label regression: ${passed} passed, ${failed} FAILED.`);
process.exit(failed === 0 ? 0 : 1);
