/**
 * NotFoundPage — 404 screen for unauthorized admin route access.
 *
 * When an unauthenticated user navigates to the admin route slug,
 * they see this generic 404 instead of a login prompt.  This avoids
 * revealing the existence of an admin interface.
 */
import React from 'react';
import { Link } from 'react-router-dom';

export function NotFoundPage() {
  return (
    <div className="not-found-container">
      <div className="not-found-content">
        <div className="not-found-code">404</div>
        <div className="not-found-title">Page Not Found</div>
        <div className="not-found-desc">
          The page you are looking for does not exist or has been moved.
        </div>
        <Link to="/" className="not-found-link">← Return to THE ARK Portal</Link>
      </div>
    </div>
  );
}
