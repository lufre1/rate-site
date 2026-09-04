// Transient, app-level feedback for actions with nowhere to put a message.
//
// This exists because a dozen call sites failed in complete silence: a vote
// that did not register, an Account row whose DELETE failed and simply stayed,
// a /meals-summary request whose failure silently voided every "aktuell"
// average on the page. Those actions have no form and no obvious slot for an
// inline error, which is what a toast is for.
//
// It is deliberately NOT used for the review-submit confirmation. The reported
// complaint there was locational -- "where did my comment go" -- and a
// self-dismissing message would recreate exactly that. See .rating-form__status.
import React, { createContext, useCallback, useContext, useState } from 'react';
import { useTranslation } from 'react-i18next';

// A no-op default, so a component rendered outside the provider (a test that
// mounts one piece in isolation) does not have to care.
const ToastContext = createContext(() => {});

// Errors linger: a failure usually needs a decision, a confirmation does not.
const DURATION = { error: 6000, success: 4000 };

let seq = 0;

export function ToastProvider({ children }) {
  const { t } = useTranslation();
  const [toasts, setToasts] = useState([]);

  const dismiss = useCallback((id) => {
    setToasts(list => list.filter(item => item.id !== id));
  }, []);

  const notify = useCallback((message, tone = 'error') => {
    if (!message) return;
    seq += 1;
    const id = seq;
    setToasts(list => [...list, { id, message, tone }]);
    setTimeout(() => dismiss(id), DURATION[tone] ?? DURATION.error);
  }, [dismiss]);

  return (
    <ToastContext.Provider value={notify}>
      {children}
      {/* Mounted unconditionally: a live region inserted together with its
          text is not reliably announced. Sits at the app root rather than
          inside the menu, so it is outside that subtree's own live region. */}
      <div className="toast-host" role="status" aria-live="polite">
        {toasts.map(item => (
          <div key={item.id} className="toast" data-tone={item.tone}>
            <span className="toast__text">{item.message}</span>
            <button
              type="button"
              className="toast__close"
              onClick={() => dismiss(item.id)}
              title={t('ui.close')}
              aria-label={t('ui.close')}
            >
              <span aria-hidden="true">&times;</span>
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

// Returns notify(message, tone) where tone is 'error' (default) or 'success'.
export function useToast() {
  return useContext(ToastContext);
}
