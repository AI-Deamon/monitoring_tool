import os
import shutil
import subprocess
import unittest

JS_PATH = os.path.join(os.path.dirname(__file__), '..', 'server', 'static', 'js', 'custom_datepicker.js')


def run_node_datepicker_tests():
    """Runs a comprehensive suite of DOM assertions against custom_datepicker.js using JSDOM in Node.js."""
    test_script = r"""
const fs = require('fs');
const { JSDOM } = require('jsdom');

const dpSrc = fs.readFileSync(process.argv[1], 'utf8');

const html = `<!DOCTYPE html>
<html>
<head></head>
<body>
    <div id="test-container">
        <input type="date" id="test-date" value="2026-10-09">
        <input type="date" id="bounded-date" min="2024-02-10" max="2024-02-20" value="2024-02-15">
        <input type="date" id="empty-date">
    </div>
</body>
</html>`;

const dom = new JSDOM(html, { runScripts: "dangerously" });
const { window } = dom;
const { document } = window;

// Provide window/document globals and mock requestAnimationFrame
window.requestAnimationFrame = (cb) => setTimeout(cb, 0);

// Execute custom_datepicker.js in window context
window.eval(dpSrc);

const SeCustomDatePicker = window.SeCustomDatePicker;
const cases = [];
function check(name, condition, extraInfo = '') {
    if (condition) {
        cases.push(`PASS: ${name}`);
    } else {
        cases.push(`FAIL: ${name} ${extraInfo}`);
    }
}

// --------------------------------------------------------------------------
// TEST 1: DOM Structure & Initial State
// --------------------------------------------------------------------------
const inputEl = document.getElementById('test-date');
const dp = new SeCustomDatePicker(inputEl);

check('Instance created', !!dp);
check('Wrapper created with class', dp.wrapper.classList.contains('se-custom-datepicker-wrapper'));
check('Trigger button created', !!dp.btn);
check('Trigger button label shows Oct 09, 2026', dp.label.textContent === 'Oct 09, 2026', `got: "${dp.label.textContent}"`);
check('Panel has role="dialog"', dp.panel.getAttribute('role') === 'dialog');
check('Prev button exists with aria-label', dp.prevBtn && dp.prevBtn.getAttribute('aria-label') === 'Previous month');
check('Next button exists with aria-label', dp.nextBtn && dp.nextBtn.getAttribute('aria-label') === 'Next month');
check('Month button exists with aria-label', dp.monthBtn && dp.monthBtn.getAttribute('aria-label') === 'Select month');
check('Year button exists with aria-label', dp.yearBtn && dp.yearBtn.getAttribute('aria-label') === 'Select year');
check('Month text shows Oct', dp.monthText.textContent === 'Oct', `got: "${dp.monthText.textContent}"`);
check('Year text shows 2026', dp.yearText.textContent === '2026', `got: "${dp.yearText.textContent}"`);
check('Footer Clear and Today buttons exist', !!dp.clearBtn && !!dp.todayBtn);

// --------------------------------------------------------------------------
// TEST 2: Open Panel & Days Grid
// --------------------------------------------------------------------------
dp.open();
check('Panel is open', dp.isOpen());
check('Panel style is block', dp.panel.style.display === 'block');
check('Selected day is Oct 9', !!dp.daysEl.querySelector('.se-day--selected[data-date="2026-10-09"]'));
check('Total calendar cells is 35 or 42', [35, 42].includes(dp.daysEl.querySelectorAll('.se-dp-day').length));

// --------------------------------------------------------------------------
// TEST 3: Independent Month Dropdown Grid
// --------------------------------------------------------------------------
dp.monthBtn.click();
check('View mode switched to month', dp.viewMode === 'month');
check('Month button has active class', dp.monthBtn.classList.contains('se-header-btn--active'));
check('Month button aria-expanded is true', dp.monthBtn.getAttribute('aria-expanded') === 'true');
check('Month grid contains 12 months', dp.monthView.querySelectorAll('.se-dp-month-item').length === 12);

// Select February (index 1)
const febBtn = dp.monthView.querySelector('button[data-month="1"]');
check('Feb month button found', !!febBtn);
febBtn.click();

check('View mode returned to days', dp.viewMode === 'days');
check('Picker remains open after month selection', dp.isOpen());
check('Header month text updated to Feb', dp.monthText.textContent === 'Feb', `got: "${dp.monthText.textContent}"`);
check('Days grid updated to February', !!dp.daysEl.querySelector('[data-date="2026-02-01"]'));

// --------------------------------------------------------------------------
// TEST 4: Independent Year Dropdown & Distant Year Selection
// --------------------------------------------------------------------------
dp.yearBtn.click();
check('View mode switched to year', dp.viewMode === 'year');
check('Year button has active class', dp.yearBtn.classList.contains('se-header-btn--active'));
check('Year button aria-expanded is true', dp.yearBtn.getAttribute('aria-expanded') === 'true');

// Select 2024
const y2024Btn = dp.yearGrid.querySelector('button[data-year="2024"]');
check('Year 2024 button found', !!y2024Btn);
y2024Btn.click();

check('View mode returned to days after year selection', dp.viewMode === 'days');
check('Picker remains open after year selection', dp.isOpen());
check('Header year text updated to 2024', dp.yearText.textContent === '2024', `got: "${dp.yearText.textContent}"`);

// --------------------------------------------------------------------------
// TEST 5: Leap Year 2024 (February 2024 has 29 days)
// --------------------------------------------------------------------------
const feb29_2024 = dp.daysEl.querySelector('.se-dp-day[data-date="2024-02-29"]');
check('February 2024 has day 29 (leap year)', !!feb29_2024 && !feb29_2024.classList.contains('se-day--other-month'));

// Switch to 2025: February 2025 has 28 days
dp.yearBtn.click();
const y2025Btn = dp.yearGrid.querySelector('button[data-year="2025"]');
y2025Btn.click();
const feb29_2025 = dp.daysEl.querySelector('.se-dp-day[data-date="2025-02-29"]:not(.se-day--other-month)');
check('February 2025 does NOT have day 29 in month', !feb29_2025);

// --------------------------------------------------------------------------
// TEST 6: Month End Transition (e.g. Jan 31 -> Feb)
// --------------------------------------------------------------------------
inputEl.value = '2024-01-31';
dp.syncFromInput();
check('Current view is Jan 2024', dp.monthText.textContent === 'Jan');
dp.nextBtn.click(); // Next month -> Feb
check('Navigated from Jan 31 to Feb without jump to March', dp.monthText.textContent === 'Feb' && dp.yearText.textContent === '2024');

// --------------------------------------------------------------------------
// TEST 7: Day Selection & Event Dispatching
// --------------------------------------------------------------------------
let inputEventFired = false;
let changeEventFired = false;
inputEl.addEventListener('input', () => { inputEventFired = true; });
inputEl.addEventListener('change', () => { changeEventFired = true; });

const day14Btn = dp.daysEl.querySelector('.se-dp-day[data-date="2024-02-14"]');
check('Day 2024-02-14 button exists', !!day14Btn);
day14Btn.click();

check('Input value updated to 2024-02-14', inputEl.value === '2024-02-14', `got: "${inputEl.value}"`);
check('Input event fired', inputEventFired);
check('Change event fired', changeEventFired);
check('Trigger button label updated to Feb 14, 2024', dp.label.textContent === 'Feb 14, 2024', `got: "${dp.label.textContent}"`);
check('Panel closed after date selection', !dp.isOpen());

// --------------------------------------------------------------------------
// TEST 8: Programmatic value assignment via property hook
// --------------------------------------------------------------------------
inputEl.value = '2026-11-20';
check('Programmatic value change triggers label update to Nov 20, 2026', dp.label.textContent === 'Nov 20, 2026', `got: "${dp.label.textContent}"`);

// --------------------------------------------------------------------------
// TEST 9: Clear Action
// --------------------------------------------------------------------------
dp.open();
dp.clearBtn.click();
check('Clear action empties input value', inputEl.value === '');
check('Clear action resets label to Select date', dp.label.textContent === 'Select date', `got: "${dp.label.textContent}"`);
check('Panel closed after Clear', !dp.isOpen());

// --------------------------------------------------------------------------
// TEST 10: Today Action
// --------------------------------------------------------------------------
dp.open();
dp.todayBtn.click();
const now = new Date();
const todayISO = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
check('Today action sets input value to today', inputEl.value === todayISO, `got: "${inputEl.value}" vs "${todayISO}"`);
check('Panel closed after Today', !dp.isOpen());

// --------------------------------------------------------------------------
// TEST 11: Min and Max Constraints & Disabled Dates
// --------------------------------------------------------------------------
const boundedInput = document.getElementById('bounded-date');
const boundedDp = new SeCustomDatePicker(boundedInput);
boundedDp.open();

// Bounded input: min="2024-02-10", max="2024-02-20"
const beforeMinDay = boundedDp.daysEl.querySelector('.se-dp-day[data-date="2024-02-05"]');
const inRangeDay = boundedDp.daysEl.querySelector('.se-dp-day[data-date="2024-02-15"]');
const afterMaxDay = boundedDp.daysEl.querySelector('.se-dp-day[data-date="2024-02-25"]');

check('Day before min (Feb 05) is disabled', !!beforeMinDay && beforeMinDay.disabled && beforeMinDay.classList.contains('se-day--disabled'));
check('Day in range (Feb 15) is enabled', !!inRangeDay && !inRangeDay.disabled);
check('Day after max (Feb 25) is disabled', !!afterMaxDay && afterMaxDay.disabled && afterMaxDay.classList.contains('se-day--disabled'));

// Month view with bounds
boundedDp.monthBtn.click();
const marchMonthBtn = boundedDp.monthView.querySelector('button[data-month="2"]'); // March
check('March month button is disabled when max is Feb 2024', !!marchMonthBtn && marchMonthBtn.disabled);
boundedDp.close();

// --------------------------------------------------------------------------
// TEST 12: Keyboard Escape & Outside Click Dismissal
// --------------------------------------------------------------------------
dp.open();
dp.monthBtn.click();
check('Month view active before Escape', dp.viewMode === 'month');

// Escape while in month view should revert to days view
const escEvent1 = new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true });
document.dispatchEvent(escEvent1);
check('Escape in month view returns to days view', dp.viewMode === 'days');
check('Picker remains open after first Escape', dp.isOpen());

// Escape while in days view should close the picker
const escEvent2 = new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true });
document.dispatchEvent(escEvent2);
check('Escape in days view closes the panel', !dp.isOpen());

// Outside click dismissal
dp.open();
check('Panel opened for outside click test', dp.isOpen());
const outsideClick = new window.MouseEvent('click', { bubbles: true });
document.body.dispatchEvent(outsideClick);
check('Outside click dismisses open picker', !dp.isOpen());

// --------------------------------------------------------------------------
// TEST 13: Auto-Enhance Utility
// --------------------------------------------------------------------------
const emptyInput = document.getElementById('empty-date');
check('Empty input not yet initialized', !emptyInput._seCustomDatePicker);
SeCustomDatePicker.enhanceAll(document);
check('Auto-enhance successfully initialized empty-date', !!emptyInput._seCustomDatePicker);

// Output results
console.log(cases.join('\n'));
if (cases.some(c => c.startsWith('FAIL'))) {
    process.exit(1);
}
"""
    r = subprocess.run(['node', '-e', test_script, JS_PATH], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


class TestCustomDatePickerComponent(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), "Node.js not available")
    def test_custom_datepicker_interactions(self):
        rc, out = run_node_datepicker_tests()
        self.assertEqual(rc, 0, f"Custom Datepicker Component assertions failed:\n{out}")
        self.assertNotIn("FAIL", out, f"Component test failed:\n{out}")
        self.assertIn("PASS: Instance created", out)
        self.assertIn("PASS: Month grid contains 12 months", out)
        self.assertIn("PASS: Header month text updated to Feb", out)
        self.assertIn("PASS: Header year text updated to 2024", out)
        self.assertIn("PASS: February 2024 has day 29 (leap year)", out)
        self.assertIn("PASS: February 2025 does NOT have day 29 in month", out)
        self.assertIn("PASS: Day before min (Feb 05) is disabled", out)
        self.assertIn("PASS: Auto-enhance successfully initialized empty-date", out)


if __name__ == '__main__':
    unittest.main()
