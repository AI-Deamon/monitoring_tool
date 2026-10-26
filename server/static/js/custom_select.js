/**
 * SentinelEdge Custom Select Component (SeCustomSelect)
 * Visual Standard: Glassmorphic layered dropdown matching Team Overview & dashboard.css
 */
(function (global) {
    'use strict';

    class SeCustomSelect {
        constructor(selectEl, options = {}) {
            if (!selectEl || selectEl.tagName !== 'SELECT') return;

            // If already initialized on this element, refresh and return existing instance
            if (selectEl._seCustomSelect) {
                selectEl._seCustomSelect.refresh();
                return selectEl._seCustomSelect;
            }

            this.select = selectEl;
            this.options = options || {};
            this.select._seCustomSelect = this;

            this.init();
        }

        init() {
            // Hide native select visually but keep it in DOM and functional for forms/events
            this.select.classList.add('se-custom-native-hidden');
            this.select.setAttribute('tabindex', '-1');
            this.select.setAttribute('aria-hidden', 'true');

            // Build wrapper
            let wrapper = this.select.parentElement;
            if (!wrapper || !wrapper.classList.contains('se-custom-select-wrapper')) {
                wrapper = document.createElement('div');
                wrapper.className = 'se-custom-select-wrapper';
                if (this.options.align === 'right' || this.select.classList.contains('se-align-right')) {
                    wrapper.classList.add('se-dropdown-align-right');
                }
                // Inherit any max-w sizing from select
                Array.from(this.select.classList).forEach(cls => {
                    if (cls.startsWith('max-w-')) wrapper.classList.add(cls);
                });

                this.select.parentNode.insertBefore(wrapper, this.select);
                wrapper.appendChild(this.select);
            }
            this.wrapper = wrapper;

            // Remove any previous custom UI inside wrapper if present
            const oldBtn = this.wrapper.querySelector(':scope > .se-custom-select__btn');
            if (oldBtn) oldBtn.remove();
            const oldPanel = this.wrapper.querySelector(':scope > .se-custom-select__panel');
            if (oldPanel) oldPanel.remove();

            // Create Trigger Button
            this.btn = document.createElement('button');
            this.btn.type = 'button';
            this.btn.className = 'se-custom-select__btn';
            if (this.select.id) {
                this.btn.id = `${this.select.id}-btn`;
            }
            this.btn.setAttribute('aria-haspopup', 'listbox');
            this.btn.setAttribute('aria-expanded', 'false');
            if (this.select.disabled) this.btn.disabled = true;

            this.label = document.createElement('span');
            this.label.className = 'se-custom-select__label';

            this.chevron = document.createElement('span');
            this.chevron.className = 'se-custom-select__chevron';
            this.chevron.setAttribute('aria-hidden', 'true');
            this.chevron.innerHTML = `<svg class="w-4 h-4" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd"/></svg>`;

            this.btn.appendChild(this.label);
            this.btn.appendChild(this.chevron);
            this.wrapper.appendChild(this.btn);

            // Create Panel & List
            this.panel = document.createElement('div');
            this.panel.className = 'se-custom-select__panel';
            this.panel.style.display = 'none';
            this.panel.setAttribute('role', 'listbox');

            this.list = document.createElement('ul');
            this.list.className = 'se-custom-select__list';
            this.panel.appendChild(this.list);
            this.wrapper.appendChild(this.panel);

            // Populate options
            this.renderOptions();
            this.syncFromSelect();

            // Event Listeners
            this.btn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.toggle();
            });

            this.btn.addEventListener('keydown', (e) => {
                if (e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    if (!this.isOpen()) {
                        this.open();
                    } else if (e.key === 'Enter' || e.key === ' ') {
                        this.close();
                    }
                }
            });

            // Native change event listener to keep custom label in sync
            this._nativeChangeHandler = () => this.syncFromSelect();
            this.select.addEventListener('change', this._nativeChangeHandler);

            // MutationObserver to auto-update when options change in native select
            if (window.MutationObserver) {
                this.observer = new MutationObserver(() => {
                    this.renderOptions();
                    this.syncFromSelect();
                });
                this.observer.observe(this.select, { childList: true, subtree: true, attributes: true, attributeFilter: ['selected', 'disabled'] });
            }
        }

        renderOptions() {
            this.list.innerHTML = '';
            const options = Array.from(this.select.options);

            options.forEach((opt, idx) => {
                const li = document.createElement('li');
                li.className = 'se-custom-select__item';
                li.setAttribute('role', 'option');
                li.setAttribute('data-value', opt.value);
                li.setAttribute('tabindex', '0');

                if (opt.disabled) {
                    li.classList.add('se-item--disabled');
                    li.setAttribute('aria-disabled', 'true');
                }

                if (opt.selected) {
                    li.classList.add('se-item--selected');
                    li.setAttribute('aria-selected', 'true');
                }

                const span = document.createElement('span');
                span.textContent = opt.textContent;
                li.appendChild(span);

                if (opt.selected) {
                    const check = document.createElement('span');
                    check.className = 'se-custom-select__item-check';
                    check.setAttribute('aria-hidden', 'true');
                    check.innerHTML = `<svg class="w-4 h-4" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>`;
                    li.appendChild(check);
                }

                li.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    if (opt.disabled) return;
                    this.selectOption(opt.value);
                });

                li.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        if (opt.disabled) return;
                        this.selectOption(opt.value);
                    }
                });

                this.list.appendChild(li);
            });
        }

        selectOption(value) {
            if (this.select.value !== value) {
                this.select.value = value;
                this.select.dispatchEvent(new Event('input', { bubbles: true }));
                this.select.dispatchEvent(new Event('change', { bubbles: true }));
            }
            this.syncFromSelect();
            this.close();
            if (this.btn) this.btn.focus();
        }

        syncFromSelect() {
            const selectedOpt = this.select.options[this.select.selectedIndex] || this.select.options[0];
            const text = selectedOpt ? selectedOpt.textContent : '-- Select --';
            this.label.textContent = text;
            this.btn.title = selectedOpt ? (selectedOpt.title || selectedOpt.textContent) : '';
            this.btn.disabled = this.select.disabled;

            // Update item selected classes
            const currentVal = this.select.value;
            this.list.querySelectorAll('.se-custom-select__item').forEach(item => {
                const isSelected = item.getAttribute('data-value') === currentVal;
                item.classList.toggle('se-item--selected', isSelected);
                item.setAttribute('aria-selected', isSelected ? 'true' : 'false');

                let check = item.querySelector('.se-custom-select__item-check');
                if (isSelected && !check) {
                    check = document.createElement('span');
                    check.className = 'se-custom-select__item-check';
                    check.setAttribute('aria-hidden', 'true');
                    check.innerHTML = `<svg class="w-4 h-4" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>`;
                    item.appendChild(check);
                } else if (!isSelected && check) {
                    check.remove();
                }
            });
        }

        isOpen() {
            return this.wrapper.classList.contains('se-dropdown--open');
        }

        open() {
            // Close other open custom dropdowns
            document.querySelectorAll('.se-custom-select-wrapper.se-dropdown--open').forEach(w => {
                const sel = w.querySelector('select');
                if (sel && sel._seCustomSelect && sel._seCustomSelect !== this) {
                    sel._seCustomSelect.close();
                }
            });
            document.querySelectorAll('.se-custom-datepicker-wrapper.se-dropdown--open').forEach(w => {
                const inp = w.querySelector('input');
                if (inp && inp._seCustomDatePicker) {
                    inp._seCustomDatePicker.close();
                }
            });

            this.wrapper.classList.add('se-dropdown--open');
            this.panel.style.display = 'block';
            this.btn.setAttribute('aria-expanded', 'true');

            // Scroll selected item into view
            const selectedItem = this.list.querySelector('.se-item--selected');
            if (selectedItem) {
                selectedItem.scrollIntoView({ block: 'nearest' });
            }
        }

        close() {
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

        refresh() {
            this.renderOptions();
            this.syncFromSelect();
        }

        destroy() {
            if (this.observer) this.observer.disconnect();
            if (this._nativeChangeHandler) this.select.removeEventListener('change', this._nativeChangeHandler);
            this.select.classList.remove('se-custom-native-hidden');
            this.select.removeAttribute('tabindex');
            this.select.removeAttribute('aria-hidden');
            if (this.btn) this.btn.remove();
            if (this.panel) this.panel.remove();
            delete this.select._seCustomSelect;
        }
    }

    // Dismiss on outside click & escape
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.se-custom-select-wrapper')) {
            document.querySelectorAll('.se-custom-select-wrapper.se-dropdown--open').forEach(w => {
                const sel = w.querySelector('select');
                if (sel && sel._seCustomSelect) sel._seCustomSelect.close();
            });
        }
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            document.querySelectorAll('.se-custom-select-wrapper.se-dropdown--open').forEach(w => {
                const sel = w.querySelector('select');
                if (sel && sel._seCustomSelect) sel._seCustomSelect.close();
            });
        }
    });

    global.SeCustomSelect = SeCustomSelect;
})(typeof window !== 'undefined' ? window : this);
