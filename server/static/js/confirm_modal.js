/**
 * SentinelEdge Global Confirmation Modal System (SentinelConfirm)
 * Visual Standard: Glassmorphic layered 3D modal matching reference spec & dashboard.css
 *
 * Usage:
 *   const confirmed = await SentinelConfirm.show({
 *       title: 'Fleet-Wide Deployment',
 *       message: 'Deploy version v2.7.0 to ALL agents across the fleet?',
 *       confirmText: 'Deploy All',
 *       cancelText: 'Cancel',
 *       variant: 'primary', // 'primary' | 'danger' | 'warning' | 'info'
 *       icon: 'refresh'     // 'refresh' | 'bolt' | 'trash' | 'warning' | 'check' | 'info'
 *   });
 */
(function (global) {
    'use strict';

    // SVG icon library for confirmation modal badges
    const ICONS = {
        refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>',
        bolt: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg>',
        warning: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>',
        trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>',
        check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 13l4 4L19 7"></path></svg>',
        info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>'
    };

    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function formatMessage(message) {
        if (!message) return '';
        const raw = String(message);
        const paragraphs = raw.split(/\n{2,}/);
        return paragraphs.map(function (p) {
            const lines = p.split('\n').map(escapeHtml).join('<br>');
            return '<p class="se-confirm-modal__paragraph">' + lines + '</p>';
        }).join('');
    }

    function getIconSvg(iconName, variant) {
        if (iconName && ICONS[iconName]) {
            return ICONS[iconName];
        }
        switch (variant) {
            case 'danger':
                return ICONS.trash;
            case 'warning':
                return ICONS.warning;
            case 'info':
                return ICONS.info;
            case 'primary':
            default:
                return ICONS.bolt;
        }
    }

    const SentinelConfirm = {
        /**
         * Displays a modal confirmation dialog.
         * @param {Object} options
         * @param {string} [options.title='Confirm Action']
         * @param {string} [options.message='Are you sure you want to proceed?']
         * @param {string} [options.confirmText='Confirm']
         * @param {string} [options.cancelText='Cancel']
         * @param {string} [options.variant='primary'] - 'primary', 'danger', 'warning', or 'info'
         * @param {string} [options.icon] - 'refresh', 'bolt', 'warning', 'trash', 'check', 'info'
         * @returns {Promise<boolean>} Resolves to true if confirmed, false if cancelled or dismissed.
         */
        show: function (options) {
            options = options || {};

            // Fallback for non-browser or non-DOM environments
            if (typeof document === 'undefined' || !document.body) {
                if (typeof global.confirm === 'function') {
                    return Promise.resolve(global.confirm(options.message || 'Are you sure?'));
                }
                return Promise.resolve(true);
            }

            const title = options.title || 'Confirm Action';
            const message = options.message || 'Are you sure you want to proceed?';
            const confirmText = options.confirmText || 'Confirm';
            const cancelText = options.cancelText !== undefined ? options.cancelText : 'Cancel';
            const variant = ['primary', 'danger', 'warning', 'info'].includes(options.variant)
                ? options.variant
                : 'primary';
            const iconSvg = getIconSvg(options.icon, variant);

            return new Promise(function (resolve) {
                // Remove any existing active confirmation modal first
                const existing = document.getElementById('se-confirm-modal-backdrop');
                if (existing && existing.parentNode) {
                    existing.parentNode.removeChild(existing);
                }

                const prevActiveElement = document.activeElement;

                // Create backdrop element
                const backdrop = document.createElement('div');
                backdrop.id = 'se-confirm-modal-backdrop';
                backdrop.className = 'se-confirm-modal__backdrop se-confirm-variant--' + variant;
                backdrop.setAttribute('aria-hidden', 'true');

                // Render inner structure matching CSS specifications
                const cancelBtnHtml = cancelText
                    ? '<button type="button" class="se-confirm-modal__btn se-confirm-modal__btn-cancel" id="se-confirm-btn-cancel">' + escapeHtml(cancelText) + '</button>'
                    : '';

                backdrop.innerHTML =
                    '<div class="se-confirm-modal__frame" role="dialog" aria-modal="true" aria-labelledby="se-confirm-title" aria-describedby="se-confirm-desc">' +
                        '<div class="se-confirm-modal__layer-back"></div>' +
                        '<div class="se-confirm-modal__layer-mid"></div>' +
                        '<div class="se-confirm-modal__card">' +
                            '<button type="button" class="se-confirm-modal__close-btn" id="se-confirm-btn-close" aria-label="Close dialog">' +
                                '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">' +
                                    '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>' +
                                '</svg>' +
                            '</button>' +
                            '<div class="se-confirm-modal__illustration-area">' +
                                '<div class="se-confirm-modal__halo"></div>' +
                                '<div class="se-confirm-modal__cards-stack">' +
                                    '<div class="se-stack-card se-stack-card-back">' +
                                        '<div class="se-stack-card-header">' +
                                            '<span class="se-dot"></span><span class="se-dot"></span><span class="se-dot"></span>' +
                                        '</div>' +
                                    '</div>' +
                                    '<div class="se-stack-card se-stack-card-mid">' +
                                        '<div class="se-stack-card-header">' +
                                            '<span class="se-dot"></span><span class="se-dot"></span><span class="se-dot"></span>' +
                                        '</div>' +
                                    '</div>' +
                                '</div>' +
                                '<div class="se-confirm-modal__sparkles">' +
                                    '<span class="se-sparkle se-sparkle-1"></span>' +
                                    '<span class="se-sparkle se-sparkle-2"></span>' +
                                    '<span class="se-sparkle se-sparkle-3"></span>' +
                                '</div>' +
                                '<div class="se-confirm-modal__icon-badge">' +
                                    '<div class="se-confirm-modal__icon-disc">' +
                                        iconSvg +
                                    '</div>' +
                                '</div>' +
                            '</div>' +
                            '<div class="se-confirm-modal__body">' +
                                '<h3 id="se-confirm-title" class="se-confirm-modal__title">' + escapeHtml(title) + '</h3>' +
                                '<div id="se-confirm-desc" class="se-confirm-modal__message">' + formatMessage(message) + '</div>' +
                            '</div>' +
                            '<div class="se-confirm-modal__actions">' +
                                cancelBtnHtml +
                                '<button type="button" class="se-confirm-modal__btn se-confirm-modal__btn-confirm" id="se-confirm-btn-confirm">' + escapeHtml(confirmText) + '</button>' +
                            '</div>' +
                        '</div>' +
                    '</div>';

                document.body.appendChild(backdrop);

                const cardEl = backdrop.querySelector('.se-confirm-modal__card');
                const confirmBtn = backdrop.querySelector('#se-confirm-btn-confirm');
                const cancelBtn = backdrop.querySelector('#se-confirm-btn-cancel');
                const closeBtn = backdrop.querySelector('#se-confirm-btn-close');

                let isClosed = false;

                function close(result) {
                    if (isClosed) return;
                    isClosed = true;

                    document.removeEventListener('keydown', handleKeyDown);
                    backdrop.classList.remove('se-confirm-modal--visible');
                    backdrop.setAttribute('aria-hidden', 'true');
                    document.body.classList.remove('se-modal-locked');

                    // Allow exit transition to complete before removing from DOM
                    setTimeout(function () {
                        if (backdrop.parentNode) {
                            backdrop.parentNode.removeChild(backdrop);
                        }
                        if (prevActiveElement && typeof prevActiveElement.focus === 'function') {
                            try { prevActiveElement.focus(); } catch (e) {}
                        }
                        resolve(result);
                    }, 240);
                }

                // Keyboard handling (Escape to cancel & focus trap)
                function handleKeyDown(e) {
                    if (e.key === 'Escape') {
                        e.preventDefault();
                        close(false);
                        return;
                    }

                    if (e.key === 'Tab') {
                        const focusable = backdrop.querySelectorAll('button:not([disabled])');
                        if (!focusable.length) return;
                        const first = focusable[0];
                        const last = focusable[focusable.length - 1];

                        if (e.shiftKey) {
                            if (document.activeElement === first) {
                                e.preventDefault();
                                last.focus();
                            }
                        } else {
                            if (document.activeElement === last) {
                                e.preventDefault();
                                first.focus();
                            }
                        }
                    }
                }

                // Click event listeners
                if (confirmBtn) {
                    confirmBtn.addEventListener('click', function () { close(true); });
                }
                if (cancelBtn) {
                    cancelBtn.addEventListener('click', function () { close(false); });
                }
                if (closeBtn) {
                    closeBtn.addEventListener('click', function () { close(false); });
                }

                // Click on outside backdrop dismisses
                backdrop.addEventListener('click', function (e) {
                    if (cardEl && !cardEl.contains(e.target)) {
                        close(false);
                    }
                });

                document.addEventListener('keydown', handleKeyDown);

                // Show with animation on next tick
                requestAnimationFrame(function () {
                    backdrop.classList.add('se-confirm-modal--visible');
                    backdrop.setAttribute('aria-hidden', 'false');
                    document.body.classList.add('se-modal-locked');

                    // Focus primary action (or cancel button if danger)
                    if (variant === 'danger' && cancelBtn) {
                        cancelBtn.focus();
                    } else if (confirmBtn) {
                        confirmBtn.focus();
                    }
                });
            });
        },

        /**
         * Convenience alert dialog with a single acknowledgment button.
         */
        alert: function (options) {
            if (typeof options === 'string') {
                options = { message: options };
            }
            options = Object.assign({}, options, {
                cancelText: null,
                confirmText: options.confirmText || 'OK'
            });
            return this.show(options);
        }
    };

    global.SentinelConfirm = SentinelConfirm;

})(typeof window !== 'undefined' ? window : this);
