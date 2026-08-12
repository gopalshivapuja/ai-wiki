import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';

/** Start every navigation at the top of the document.
 *
 * A single-page app keeps the scroll position across route changes, so following a link from
 * halfway down a long note dropped you into the middle of the next one.
 */
export function ScrollToTop() {
  const { pathname } = useLocation();

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior });
  }, [pathname]);

  return null;
}
