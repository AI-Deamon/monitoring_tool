/**
 * SentinelEdge Custom Datepicker Component (SeCustomDatePicker)
 * Standardized date picker across the application.
 * Features:
 *  - Independent Month and Year dropdown selectors in calendar header
 *  - Quick adjacent-month navigation arrows (< and >)
 *  - 12-month compact selectable grid
 *  - Scrollable year grid for fast selection of distant years
 *  - Preserves calendar grid, selected indicator, and native input synchronization
 *  - Clear and Today actions
 *  - Min / Max date constraints, disabled dates, boundary handling, leap year calculation
 *  - Dark and Light mode theme support matching dashboard tokens
 *  - Full keyboard accessibility (Arrow navigation, Enter, Space, Escape) and ARIA semantics
 *  - Viewport-aware positioning to prevent clipping in modals and page edges
 */
(function (global) {
    'use strict';

    if (typeof document === 'undefined') {
        // Node / test environment guard
        if (typeof module !== 'undefined' && module.exports) {
            module.exports = {};
        }
        return;
    }

    const MONTH_NAMES = [
        'January', 'February', 'March', 'April', 'May', 'June',
        'July', 'August', 'September', 'October', 'November', 'December'
    ];

    const MONTH_SHORT = [
        'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
        'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'
    ];

    const WEEKDAYS = [
        { label: 'Su', title: 'Sunday' },
        { label: 'Mo', title: 'Monday' },
        { label: 'Tu', title: 'Tuesday' },
        { label: 'We', title: 'Wednesday' },
        { label: 'Th', title: 'Thursday' },
        { label: 'Fr', title: 'Friday' },
        { label: 'Sa', title: 'Saturday' }
    ];

    function padZero(n) {
        return n < 10 ? '0' + n : String(n);
    }

    function formatDateISO(d) {
        if (!d || !(d instanceof Date) || isNaN(d.getTime())) return '';
        return `${d.getFullYear()}-${padZero(d.getMonth() + 1)}-${padZero(d.getDate())}`;
    }

    function parseDateISO(str) {
        if (!str || typeof str !== 'string') return null;
        const parts = str.trim().split('-');
        if (parts.length !== 3) return null;
        const y = parseInt(parts[0], 10);
        const m = parseInt(parts[1], 10) - 1;
        const d = parseInt(parts[2], 10);
        if (isNaN(y) || isNaN(m) || isNaN(d)) return null;
        if (m < 0 || m > 11 || d < 1 || d > 31) return null;
        const dt = new Date(y, m, d);
        if (dt.getFullYear() !== y || dt.getMonth() !== m || dt.getDate() !== d) return null;
        return dt;
    }

    function formatDisplayDate(dateStr, fallback = 'Select date') {
        const dt = parseDateISO(dateStr);
        if (!dt) return fallback;
        return `${MONTH_SHORT[dt.getMonth()]} ${padZero(dt.getDate())}, ${dt.getFullYear()}`;
    }

    function getLocalTodayISO() {
        if (typeof window !== 'undefined' && typeof window.localDateStr === 'function') {
            try {
                return window.localDateStr();
            } catch (e) {
                // fallback
            }
        }
        const now = new Date();
        return `${now.getFullYear()}-${padZero(now.getMonth() + 1)}-${padZero(now.getDate())}`;
    }

    class SeCustomDatePicker {
        constructor(inputEl, options = {}) {
            if (!inputEl || inputEl.tagName !== 'INPUT') return;

            if (inputEl._seCustomDatePicker) {
                inputEl._seCustomDatePicker.syncFromInput();
                return inputEl._seCustomDatePicker;
            }

            this.input = inputEl;
            this.options = options || {};
            this.input._seCustomDatePicker = this;

            // Current view state: 'days' | 'month' | 'year'
            this.viewMode = 'days';

            // Active calendar anchor date
            const initialDate = parseDateISO(this.input.value);
            this.currentViewDate = initialDate ? new Date(initialDate.getTime()) : parseDateISO(getLocalTodayISO()) || new Date();
            // Anchor to day 1 to prevent month-end rollover bugs when jumping months
            this.currentViewDate = new Date(this.currentViewDate.getFullYear(), this.currentViewDate.getMonth(), 1);

            this.init();
            this.hookInputValueProperty();
        }

        parseDate(str) {
            return parseDateISO(str);
        }

        formatDate(d) {
            return formatDateISO(d);
        }

        getMinDate() {
            const minStr = this.input.getAttribute('min');
            return minStr ? parseDateISO(minStr) : null;
        }

        getMaxDate() {
            const maxStr = this.input.getAttribute('max');
            return maxStr ? parseDateISO(maxStr) : null;
        }

        isDateDisabled(d) {
            if (!d) return false;
            const str = formatDateISO(d);
            const min = this.getMinDate();
            if (min && str < formatDateISO(min)) return true;
            const max = this.getMaxDate();
            if (max && str > formatDateISO(max)) return true;
            return false;
        }

        hookInputValueProperty() {
            // Intercept direct programmatic assignment to input.value (e.g. input.value = '2026-10-09')
            if (this._valueHooked) return;
            this._valueHooked = true;
            const descriptor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
            if (!descriptor) return;

            const self = this;
            Object.defineProperty(this.input, 'value', {
                get() {
                    return descriptor.get.call(this);
                },
                set(val) {
                    descriptor.set.call(this, val);
                    self.syncFromInput();
                },
                configurable: true
            });
        }

        init() {
            // Hide native input visually but keep functional for form submission & events
            this.input.classList.add('se-custom-native-hidden');
            this.input.setAttribute('tabindex', '-1');
            this.input.setAttribute('aria-hidden', 'true');

            // Build or reuse wrapper
            let wrapper = this.input.parentElement;
            if (!wrapper || !wrapper.classList.contains('se-custom-datepicker-wrapper')) {
                wrapper = document.createElement('div');
                wrapper.className = 'se-custom-datepicker-wrapper';
                if (this.options.isHeader) {
                    wrapper.classList.add('se-header-datepicker');
                }
                Array.from(this.input.classList).forEach(cls => {
                    if (cls.startsWith('max-w-') || cls === 'w-full') wrapper.classList.add(cls);
                });

                this.input.parentNode.insertBefore(wrapper, this.input);
                wrapper.appendChild(this.input);
            } else if (this.options.isHeader && !wrapper.classList.contains('se-header-datepicker')) {
                wrapper.classList.add('se-header-datepicker');
            }
            this.wrapper = wrapper;

            // Remove any old UI
            const oldBtn = this.wrapper.querySelector(':scope > .se-datepicker__btn');
            if (oldBtn) oldBtn.remove();
            const oldPanel = this.wrapper.querySelector(':scope > .se-datepicker__panel');
            if (oldPanel) oldPanel.remove();

            // Trigger button
            this.btn = document.createElement('button');
            this.btn.type = 'button';
            this.btn.className = 'se-datepicker__btn';
            if (this.input.id) {
                this.btn.id = `${this.input.id}-btn`;
            }
            this.btn.setAttribute('aria-haspopup', 'dialog');
            this.btn.setAttribute('aria-expanded', 'false');
            this.btn.setAttribute('aria-label', this.input.getAttribute('aria-label') || 'Select date');
            if (this.input.disabled) this.btn.disabled = true;

            this.label = document.createElement('span');
            this.label.className = 'se-datepicker__label';

            this.icon = document.createElement('span');
            this.icon.className = 'se-datepicker__icon';
            this.icon.setAttribute('aria-hidden', 'true');
            this.icon.innerHTML = `<svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>`;

            this.btn.appendChild(this.label);
            this.btn.appendChild(this.icon);
            this.wrapper.appendChild(this.btn);

            // Calendar Panel
            this.panel = document.createElement('div');
            this.panel.className = 'se-datepicker__panel';
            this.panel.style.display = 'none';
            this.panel.setAttribute('role', 'dialog');
            this.panel.setAttribute('aria-modal', 'false');
            this.panel.setAttribute('aria-label', 'Calendar date picker');

            // Calendar Header (Prev nav, Month dropdown, Year dropdown, Next nav)
            this.buildHeader();

            // Views Container (Days view, Month grid view, Year grid view)
            this.viewsContainer = document.createElement('div');
            this.viewsContainer.className = 'se-dp-views-container';
            this.panel.appendChild(this.viewsContainer);

            // Build subviews
            this.buildDaysView();
            this.buildMonthView();
            this.buildYearView();

            // Footer (Clear & Today actions)
            this.buildFooter();

            this.wrapper.appendChild(this.panel);

            // Sync from initial input state
            this.syncFromInput();
            this.setViewMode('days');

            // Wire Trigger Events
            this.btn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.toggle();
            });

            this.btn.addEventListener('keydown', (e) => {
                if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    if (!this.isOpen()) this.open();
                }
            });

            this._nativeChangeHandler = () => this.syncFromInput();
            this.input.addEventListener('change', this._nativeChangeHandler);
            this.input.addEventListener('input', this._nativeChangeHandler);
        }

        buildHeader() {
            this.header = document.createElement('div');
            this.header.className = 'se-dp-header';

            // Previous Month Button
            this.prevBtn = document.createElement('button');
            this.prevBtn.type = 'button';
            this.prevBtn.className = 'se-dp-nav-btn se-dp-prev';
            this.prevBtn.setAttribute('aria-label', 'Previous month');
            this.prevBtn.innerHTML = `<svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7"/></svg>`;

            // Center Dropdown Selectors (Month and Year)
            this.selectorsWrap = document.createElement('div');
            this.selectorsWrap.className = 'se-dp-selectors';

            // Month Dropdown Trigger
            this.monthBtn = document.createElement('button');
            this.monthBtn.type = 'button';
            this.monthBtn.className = 'se-dp-header-btn se-dp-month-btn';
            this.monthBtn.setAttribute('aria-haspopup', 'grid');
            this.monthBtn.setAttribute('aria-expanded', 'false');
            this.monthBtn.setAttribute('aria-label', 'Select month');
            this.monthText = document.createElement('span');
            this.monthText.className = 'se-dp-header-btn-text';
            this.monthChevron = document.createElement('span');
            this.monthChevron.className = 'se-dp-header-chevron';
            this.monthChevron.innerHTML = `<svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd"/></svg>`;
            this.monthBtn.appendChild(this.monthText);
            this.monthBtn.appendChild(this.monthChevron);

            // Year Dropdown Trigger
            this.yearBtn = document.createElement('button');
            this.yearBtn.type = 'button';
            this.yearBtn.className = 'se-dp-header-btn se-dp-year-btn';
            this.yearBtn.setAttribute('aria-haspopup', 'grid');
            this.yearBtn.setAttribute('aria-expanded', 'false');
            this.yearBtn.setAttribute('aria-label', 'Select year');
            this.yearText = document.createElement('span');
            this.yearText.className = 'se-dp-header-btn-text';
            this.yearChevron = document.createElement('span');
            this.yearChevron.className = 'se-dp-header-chevron';
            this.yearChevron.innerHTML = `<svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd"/></svg>`;
            this.yearBtn.appendChild(this.yearText);
            this.yearBtn.appendChild(this.yearChevron);

            this.selectorsWrap.appendChild(this.monthBtn);
            this.selectorsWrap.appendChild(this.yearBtn);

            // Next Month Button
            this.nextBtn = document.createElement('button');
            this.nextBtn.type = 'button';
            this.nextBtn.className = 'se-dp-nav-btn se-dp-next';
            this.nextBtn.setAttribute('aria-label', 'Next month');
            this.nextBtn.innerHTML = `<svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7"/></svg>`;

            this.header.appendChild(this.prevBtn);
            this.header.appendChild(this.selectorsWrap);
            this.header.appendChild(this.nextBtn);
            this.panel.appendChild(this.header);

            // Navigation Clicks
            this.prevBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                if (this.viewMode !== 'days') {
                    this.setViewMode('days');
                }
                this.navigateMonth(-1);
            });

            this.nextBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                if (this.viewMode !== 'days') {
                    this.setViewMode('days');
                }
                this.navigateMonth(1);
            });

            // Month Dropdown Click
            this.monthBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.setViewMode(this.viewMode === 'month' ? 'days' : 'month');
            });

            // Year Dropdown Click
            this.yearBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.setViewMode(this.viewMode === 'year' ? 'days' : 'year');
            });
        }

        buildDaysView() {
            this.daysView = document.createElement('div');
            this.daysView.className = 'se-dp-view se-dp-days-view';

            // Weekdays Row
            const weekdaysEl = document.createElement('div');
            weekdaysEl.className = 'se-dp-weekdays';
            weekdaysEl.setAttribute('role', 'row');
            WEEKDAYS.forEach(w => {
                const sp = document.createElement('span');
                sp.className = 'se-dp-weekday';
                sp.textContent = w.label;
                sp.setAttribute('title', w.title);
                sp.setAttribute('aria-label', w.title);
                sp.setAttribute('role', 'columnheader');
                weekdaysEl.appendChild(sp);
            });
            this.daysView.appendChild(weekdaysEl);

            // Days Container Grid
            this.daysEl = document.createElement('div');
            this.daysEl.className = 'se-dp-days';
            this.daysEl.setAttribute('role', 'grid');
            this.daysEl.setAttribute('aria-label', 'Month days');
            this.daysView.appendChild(this.daysEl);

            this.viewsContainer.appendChild(this.daysView);
        }

        buildMonthView() {
            this.monthView = document.createElement('div');
            this.monthView.className = 'se-dp-view se-dp-month-grid';
            this.monthView.style.display = 'none';
            this.monthView.setAttribute('role', 'grid');
            this.monthView.setAttribute('aria-label', 'Months');

            this.viewsContainer.appendChild(this.monthView);
        }

        buildYearView() {
            this.yearView = document.createElement('div');
            this.yearView.className = 'se-dp-view se-dp-year-view';
            this.yearView.style.display = 'none';

            this.yearGrid = document.createElement('div');
            this.yearGrid.className = 'se-dp-year-grid';
            this.yearGrid.setAttribute('role', 'grid');
            this.yearGrid.setAttribute('aria-label', 'Years');
            this.yearView.appendChild(this.yearGrid);

            this.viewsContainer.appendChild(this.yearView);
        }

        buildFooter() {
            this.footer = document.createElement('div');
            this.footer.className = 'se-dp-footer';

            this.clearBtn = document.createElement('button');
            this.clearBtn.type = 'button';
            this.clearBtn.className = 'se-dp-action-btn se-dp-btn--clear';
            this.clearBtn.textContent = 'Clear';
            this.clearBtn.setAttribute('aria-label', 'Clear selected date');

            this.todayBtn = document.createElement('button');
            this.todayBtn.type = 'button';
            this.todayBtn.className = 'se-dp-action-btn se-dp-btn--today';
            this.todayBtn.textContent = 'Today';
            this.todayBtn.setAttribute('aria-label', 'Select today');

            this.footer.appendChild(this.clearBtn);
            this.footer.appendChild(this.todayBtn);
            this.panel.appendChild(this.footer);

            this.clearBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.clearDate();
            });

            this.todayBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.selectToday();
            });
        }

        setViewMode(mode) {
            this.viewMode = mode;

            // Update Header Trigger States
            if (mode === 'month') {
                this.monthBtn.classList.add('se-header-btn--active');
                this.monthBtn.setAttribute('aria-expanded', 'true');
                this.yearBtn.classList.remove('se-header-btn--active');
                this.yearBtn.setAttribute('aria-expanded', 'false');
            } else if (mode === 'year') {
                this.yearBtn.classList.add('se-header-btn--active');
                this.yearBtn.setAttribute('aria-expanded', 'true');
                this.monthBtn.classList.remove('se-header-btn--active');
                this.monthBtn.setAttribute('aria-expanded', 'false');
            } else {
                this.monthBtn.classList.remove('se-header-btn--active');
                this.monthBtn.setAttribute('aria-expanded', 'false');
                this.yearBtn.classList.remove('se-header-btn--active');
                this.yearBtn.setAttribute('aria-expanded', 'false');
            }

            // Toggle view visibility
            this.daysView.style.display = (mode === 'days') ? 'block' : 'none';
            this.monthView.style.display = (mode === 'month') ? 'grid' : 'none';
            this.yearView.style.display = (mode === 'year') ? 'block' : 'none';

            if (mode === 'days') {
                this.renderCalendar();
            } else if (mode === 'month') {
                this.renderMonthGrid();
            } else if (mode === 'year') {
                this.renderYearGrid();
            }
        }

        navigateMonth(delta) {
            const currentYear = this.currentViewDate.getFullYear();
            const currentMonth = this.currentViewDate.getMonth();
            this.currentViewDate = new Date(currentYear, currentMonth + delta, 1);
            this.renderCalendar();
        }

        renderHeaderLabels() {
            const y = this.currentViewDate.getFullYear();
            const m = this.currentViewDate.getMonth();
            this.monthText.textContent = MONTH_SHORT[m];
            this.yearText.textContent = String(y);

            // Update nav buttons disabled state according to min/max
            const min = this.getMinDate();
            const max = this.getMaxDate();

            if (min) {
                // If the entire previous month is before min
                const prevMonthEnd = new Date(y, m, 0);
                this.prevBtn.disabled = formatDateISO(prevMonthEnd) < formatDateISO(min);
            } else {
                this.prevBtn.disabled = false;
            }

            if (max) {
                // If the entire next month starts after max
                const nextMonthStart = new Date(y, m + 1, 1);
                this.nextBtn.disabled = formatDateISO(nextMonthStart) > formatDateISO(max);
            } else {
                this.nextBtn.disabled = false;
            }
        }

        renderCalendar() {
            const year = this.currentViewDate.getFullYear();
            const month = this.currentViewDate.getMonth();

            this.renderHeaderLabels();
            this.daysEl.innerHTML = '';

            const firstDayOfWeek = new Date(year, month, 1).getDay();
            const daysInMonth = new Date(year, month + 1, 0).getDate();
            const prevMonthDays = new Date(year, month, 0).getDate();

            const selectedDate = parseDateISO(this.input.value);
            const todayStr = getLocalTodayISO();
            const todayDate = parseDateISO(todayStr);
            const isTodayInView = todayDate && (todayDate.getFullYear() === year && todayDate.getMonth() === month);

            // Check if Today button should be disabled by min/max
            if (this.todayBtn && todayDate) {
                this.todayBtn.disabled = this.isDateDisabled(todayDate);
            }

            // Trailing days from previous month
            for (let i = firstDayOfWeek - 1; i >= 0; i--) {
                const dayNum = prevMonthDays - i;
                const dateObj = new Date(year, month - 1, dayNum);
                this.daysEl.appendChild(this.createDayButton(dateObj, dayNum, true, false, false));
            }

            // Current month days
            for (let d = 1; d <= daysInMonth; d++) {
                const dateObj = new Date(year, month, d);
                const isSelected = selectedDate && (
                    selectedDate.getFullYear() === year &&
                    selectedDate.getMonth() === month &&
                    selectedDate.getDate() === d
                );
                const isToday = isTodayInView && (todayDate.getDate() === d);
                this.daysEl.appendChild(this.createDayButton(dateObj, d, false, isSelected, isToday));
            }

            // Leading days of next month to complete 35 or 42 cells (5 or 6 complete rows)
            const totalCells = firstDayOfWeek + daysInMonth;
            const remaining = totalCells <= 35 ? (35 - totalCells) : (42 - totalCells);
            for (let nextD = 1; nextD <= remaining; nextD++) {
                const dateObj = new Date(year, month + 1, nextD);
                this.daysEl.appendChild(this.createDayButton(dateObj, nextD, true, false, false));
            }
        }

        createDayButton(dateObj, displayDay, isOtherMonth, isSelected, isToday) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'se-dp-day';
            btn.textContent = String(displayDay);

            const dateStr = formatDateISO(dateObj);
            btn.setAttribute('data-date', dateStr);
            btn.setAttribute('role', 'gridcell');

            // Format full label for screen readers
            const mName = MONTH_NAMES[dateObj.getMonth()];
            const wName = WEEKDAYS[dateObj.getDay()].title;
            btn.setAttribute('aria-label', `${wName}, ${mName} ${dateObj.getDate()}, ${dateObj.getFullYear()}`);

            if (isOtherMonth) btn.classList.add('se-day--other-month');
            if (isToday) btn.classList.add('se-day--today');
            if (isSelected) {
                btn.classList.add('se-day--selected');
                btn.setAttribute('aria-selected', 'true');
                btn.setAttribute('tabindex', '0');
            } else {
                btn.setAttribute('aria-selected', 'false');
                btn.setAttribute('tabindex', '-1');
            }

            if (this.isDateDisabled(dateObj)) {
                btn.disabled = true;
                btn.classList.add('se-day--disabled');
                btn.setAttribute('aria-disabled', 'true');
            }

            btn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                if (btn.disabled) return;
                this.selectDate(dateStr);
            });

            // Day button keyboard navigation
            btn.addEventListener('keydown', (e) => {
                this.handleDayKeydown(e, dateObj);
            });

            return btn;
        }

        handleDayKeydown(e, dateObj) {
            let handled = false;
            let targetDate = null;

            switch (e.key) {
                case 'ArrowLeft':
                    targetDate = new Date(dateObj.getFullYear(), dateObj.getMonth(), dateObj.getDate() - 1);
                    handled = true;
                    break;
                case 'ArrowRight':
                    targetDate = new Date(dateObj.getFullYear(), dateObj.getMonth(), dateObj.getDate() + 1);
                    handled = true;
                    break;
                case 'ArrowUp':
                    targetDate = new Date(dateObj.getFullYear(), dateObj.getMonth(), dateObj.getDate() - 7);
                    handled = true;
                    break;
                case 'ArrowDown':
                    targetDate = new Date(dateObj.getFullYear(), dateObj.getMonth(), dateObj.getDate() + 7);
                    handled = true;
                    break;
                case 'PageUp':
                    targetDate = new Date(dateObj.getFullYear(), dateObj.getMonth() - 1, dateObj.getDate());
                    handled = true;
                    break;
                case 'PageDown':
                    targetDate = new Date(dateObj.getFullYear(), dateObj.getMonth() + 1, dateObj.getDate());
                    handled = true;
                    break;
                case 'Home':
                    targetDate = new Date(dateObj.getFullYear(), dateObj.getMonth(), 1);
                    handled = true;
                    break;
                case 'End':
                    targetDate = new Date(dateObj.getFullYear(), dateObj.getMonth() + 1, 0);
                    handled = true;
                    break;
                case 'Enter':
                case ' ':
                    handled = true;
                    if (!this.isDateDisabled(dateObj)) {
                        this.selectDate(formatDateISO(dateObj));
                    }
                    break;
            }

            if (handled) {
                e.preventDefault();
                e.stopPropagation();
                if (targetDate) {
                    const targetISO = formatDateISO(targetDate);
                    // Check if month changed
                    if (targetDate.getMonth() !== this.currentViewDate.getMonth() ||
                        targetDate.getFullYear() !== this.currentViewDate.getFullYear()) {
                        this.currentViewDate = new Date(targetDate.getFullYear(), targetDate.getMonth(), 1);
                        this.renderCalendar();
                    }
                    const nextBtn = this.daysEl.querySelector(`button[data-date="${targetISO}"]`);
                    if (nextBtn) {
                        nextBtn.focus();
                    }
                }
            }
        }

        renderMonthGrid() {
            this.renderHeaderLabels();
            this.monthView.innerHTML = '';
            const currentYear = this.currentViewDate.getFullYear();
            const activeMonth = this.currentViewDate.getMonth();
            const min = this.getMinDate();
            const max = this.getMaxDate();

            MONTH_SHORT.forEach((mShort, idx) => {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'se-dp-month-item';
                btn.textContent = mShort;
                btn.setAttribute('data-month', String(idx));
                btn.setAttribute('role', 'gridcell');
                btn.setAttribute('aria-label', MONTH_NAMES[idx]);

                if (idx === activeMonth) {
                    btn.classList.add('se-month--selected');
                    btn.setAttribute('aria-selected', 'true');
                    btn.setAttribute('tabindex', '0');
                } else {
                    btn.setAttribute('aria-selected', 'false');
                    btn.setAttribute('tabindex', '-1');
                }

                // Month boundary check: if month end is before min or month start is after max
                const monthStart = new Date(currentYear, idx, 1);
                const monthEnd = new Date(currentYear, idx + 1, 0);
                if ((min && formatDateISO(monthEnd) < formatDateISO(min)) ||
                    (max && formatDateISO(monthStart) > formatDateISO(max))) {
                    btn.disabled = true;
                    btn.classList.add('se-month--disabled');
                    btn.setAttribute('aria-disabled', 'true');
                }

                btn.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    if (btn.disabled) return;
                    this.currentViewDate = new Date(currentYear, idx, 1);
                    this.setViewMode('days');
                    if (this.monthBtn) this.monthBtn.focus();
                });

                btn.addEventListener('keydown', (e) => {
                    this.handleMonthKeydown(e, idx);
                });

                this.monthView.appendChild(btn);
            });

            // Focus active month
            const activeBtn = this.monthView.querySelector('.se-month--selected');
            if (activeBtn) {
                setTimeout(() => activeBtn.focus(), 10);
            }
        }

        handleMonthKeydown(e, idx) {
            let targetIdx = null;
            if (e.key === 'ArrowLeft') targetIdx = idx - 1;
            else if (e.key === 'ArrowRight') targetIdx = idx + 1;
            else if (e.key === 'ArrowUp') targetIdx = idx - 3;
            else if (e.key === 'ArrowDown') targetIdx = idx + 3;

            if (targetIdx !== null && targetIdx >= 0 && targetIdx < 12) {
                e.preventDefault();
                const targetBtn = this.monthView.querySelector(`button[data-month="${targetIdx}"]`);
                if (targetBtn) targetBtn.focus();
            }
        }

        renderYearGrid() {
            this.renderHeaderLabels();
            this.yearGrid.innerHTML = '';
            const activeYear = this.currentViewDate.getFullYear();
            const currentMonth = this.currentViewDate.getMonth();

            const min = this.getMinDate();
            const max = this.getMaxDate();

            const minYear = min ? min.getFullYear() : Math.min(activeYear - 50, new Date().getFullYear() - 30);
            const maxYear = max ? max.getFullYear() : Math.max(activeYear + 30, new Date().getFullYear() + 30);

            for (let y = minYear; y <= maxYear; y++) {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'se-dp-year-item';
                btn.textContent = String(y);
                btn.setAttribute('data-year', String(y));
                btn.setAttribute('role', 'gridcell');
                btn.setAttribute('aria-label', String(y));

                if (y === activeYear) {
                    btn.classList.add('se-year--selected');
                    btn.setAttribute('aria-selected', 'true');
                    btn.setAttribute('tabindex', '0');
                } else {
                    btn.setAttribute('aria-selected', 'false');
                    btn.setAttribute('tabindex', '-1');
                }

                const yearStart = new Date(y, 0, 1);
                const yearEnd = new Date(y, 11, 31);
                if ((min && formatDateISO(yearEnd) < formatDateISO(min)) ||
                    (max && formatDateISO(yearStart) > formatDateISO(max))) {
                    btn.disabled = true;
                    btn.classList.add('se-year--disabled');
                    btn.setAttribute('aria-disabled', 'true');
                }

                btn.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    if (btn.disabled) return;
                    this.currentViewDate = new Date(y, currentMonth, 1);
                    this.setViewMode('days');
                    if (this.yearBtn) this.yearBtn.focus();
                });

                btn.addEventListener('keydown', (e) => {
                    this.handleYearKeydown(e, y, minYear, maxYear);
                });

                this.yearGrid.appendChild(btn);
            }

            // Scroll selected year to center of scroll container
            requestAnimationFrame(() => {
                const sel = this.yearGrid.querySelector('.se-year--selected');
                if (sel) {
                    if (typeof sel.scrollIntoView === 'function') {
                        sel.scrollIntoView({ block: 'center', inline: 'center' });
                    }
                    sel.focus();
                }
            });
        }

        handleYearKeydown(e, y, minYear, maxYear) {
            let targetY = null;
            if (e.key === 'ArrowLeft') targetY = y - 1;
            else if (e.key === 'ArrowRight') targetY = y + 1;
            else if (e.key === 'ArrowUp') targetY = y - 3;
            else if (e.key === 'ArrowDown') targetY = y + 3;

            if (targetY !== null && targetY >= minYear && targetY <= maxYear) {
                e.preventDefault();
                const targetBtn = this.yearGrid.querySelector(`button[data-year="${targetY}"]`);
                if (targetBtn) {
                    targetBtn.focus();
                    if (typeof targetBtn.scrollIntoView === 'function') {
                        targetBtn.scrollIntoView({ block: 'nearest' });
                    }
                }
            }
        }

        selectDate(dateStr) {
            this.input.value = dateStr;
            this.input.dispatchEvent(new Event('input', { bubbles: true }));
            this.input.dispatchEvent(new Event('change', { bubbles: true }));
            this.syncFromInput();
            this.close();
            if (this.btn) this.btn.focus();
        }

        clearDate() {
            this.input.value = '';
            this.input.dispatchEvent(new Event('input', { bubbles: true }));
            this.input.dispatchEvent(new Event('change', { bubbles: true }));
            this.syncFromInput();
            this.close();
            if (this.btn) this.btn.focus();
        }

        selectToday() {
            const todayStr = getLocalTodayISO();
            const todayDate = parseDateISO(todayStr);
            if (todayDate && this.isDateDisabled(todayDate)) {
                return; // Disabled by min/max
            }
            this.selectDate(todayStr);
        }

        syncFromInput() {
            const val = this.input.value;
            const placeholder = this.input.getAttribute('placeholder') || 'Select date';
            this.label.textContent = val ? formatDisplayDate(val, placeholder) : placeholder;
            this.btn.disabled = this.input.disabled;

            const parsed = parseDateISO(val);
            if (parsed) {
                this.currentViewDate = new Date(parsed.getFullYear(), parsed.getMonth(), 1);
            }
            if (this.isOpen()) {
                if (this.viewMode === 'days') this.renderCalendar();
                else if (this.viewMode === 'month') this.renderMonthGrid();
                else if (this.viewMode === 'year') this.renderYearGrid();
            }
        }

        isOpen() {
            return this.wrapper && this.wrapper.classList.contains('se-dropdown--open');
        }

        positionPanel() {
            if (!this.panel || !this.btn) return;
            this.panel.style.display = 'block';

            const btnRect = this.btn.getBoundingClientRect();
            const panelRect = this.panel.getBoundingClientRect();
            const viewportWidth = window.innerWidth || document.documentElement.clientWidth;
            const viewportHeight = window.innerHeight || document.documentElement.clientHeight;

            // Horizontal: Right-align if header or would overflow viewport right
            const wouldOverflowRight = (btnRect.left + panelRect.width) > (viewportWidth - 12);
            if (this.options.isHeader || wouldOverflowRight) {
                this.panel.style.left = 'auto';
                this.panel.style.right = '0';
            } else {
                this.panel.style.left = '0';
                this.panel.style.right = 'auto';
            }

            // Vertical: Flip to top if cramped below and space available above
            const spaceBelow = viewportHeight - btnRect.bottom;
            const spaceAbove = btnRect.top;
            if (spaceBelow < (panelRect.height + 20) && spaceAbove > (panelRect.height + 20)) {
                this.panel.style.top = 'auto';
                this.panel.style.bottom = 'calc(100% + 6px)';
            } else {
                this.panel.style.top = 'calc(100% + 6px)';
                this.panel.style.bottom = 'auto';
            }
        }

        open() {
            // Close any open custom selects or other datepickers
            document.querySelectorAll('.se-custom-select-wrapper.se-dropdown--open').forEach(w => {
                const sel = w.querySelector('select');
                if (sel && sel._seCustomSelect) sel._seCustomSelect.close();
            });
            document.querySelectorAll('.se-custom-datepicker-wrapper.se-dropdown--open').forEach(w => {
                const inp = w.querySelector('input');
                if (inp && inp._seCustomDatePicker && inp._seCustomDatePicker !== this) {
                    inp._seCustomDatePicker.close();
                }
            });

            const parsed = parseDateISO(this.input.value);
            if (parsed) {
                this.currentViewDate = new Date(parsed.getFullYear(), parsed.getMonth(), 1);
            }
            this.setViewMode('days');

            this.wrapper.classList.add('se-dropdown--open');
            this.btn.setAttribute('aria-expanded', 'true');
            this.positionPanel();

            // Focus active day
            setTimeout(() => {
                const active = this.daysEl.querySelector('.se-day--selected') ||
                               this.daysEl.querySelector('.se-day--today') ||
                               this.daysEl.querySelector('.se-dp-day:not(.se-day--other-month):not(:disabled)');
                if (active) active.focus();
            }, 30);
        }

        close() {
            this.setViewMode('days');
            this.wrapper.classList.remove('se-dropdown--open');
            this.panel.style.display = 'none';
            this.btn.setAttribute('aria-expanded', 'false');
        }

        toggle() {
            if (this.isOpen()) {
                this.close();
            } else {
                this.open();
            }
        }

        destroy() {
            if (this._nativeChangeHandler) {
                this.input.removeEventListener('change', this._nativeChangeHandler);
                this.input.removeEventListener('input', this._nativeChangeHandler);
            }
            this.input.classList.remove('se-custom-native-hidden');
            this.input.removeAttribute('tabindex');
            this.input.removeAttribute('aria-hidden');
            if (this.btn) this.btn.remove();
            if (this.panel) this.panel.remove();
            delete this.input._seCustomDatePicker;
        }
    }

    // Dismiss on outside click & escape
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.se-custom-datepicker-wrapper')) {
            document.querySelectorAll('.se-custom-datepicker-wrapper.se-dropdown--open').forEach(w => {
                const inp = w.querySelector('input');
                if (inp && inp._seCustomDatePicker) inp._seCustomDatePicker.close();
            });
        }
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            document.querySelectorAll('.se-custom-datepicker-wrapper.se-dropdown--open').forEach(w => {
                const inp = w.querySelector('input');
                if (inp && inp._seCustomDatePicker) {
                    const dp = inp._seCustomDatePicker;
                    if (dp.viewMode !== 'days') {
                        // Return to days view first
                        dp.setViewMode('days');
                    } else {
                        dp.close();
                        if (dp.btn) dp.btn.focus();
                    }
                }
            });
        }
    });

    // Auto-enhancement utility across application
    function enhanceAll(root) {
        const context = root || document;
        if (!context || !context.querySelectorAll) return;
        const dateInputs = context.querySelectorAll('input[type="date"]:not([data-no-custom-dp])');
        dateInputs.forEach(inp => {
            if (!inp._seCustomDatePicker) {
                const isHeader = inp.id === 'global-date-select' || inp.closest('.se-header-datepicker') !== null;
                new SeCustomDatePicker(inp, isHeader ? { isHeader: true } : {});
            }
        });
    }

    SeCustomDatePicker.enhanceAll = enhanceAll;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => enhanceAll(document));
    } else {
        enhanceAll(document);
    }

    global.SeCustomDatePicker = SeCustomDatePicker;
})(typeof window !== 'undefined' ? window : this);
