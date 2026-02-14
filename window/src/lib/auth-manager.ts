/**
 * Auth state manager with cross-component session expiry signaling.
 *
 * Stores server-issued session tokens (not passwords) in sessionStorage.
 * Tokens are obtained from POST /api/dashboard/auth and expire after 24h.
 */

type AuthListener = () => void;

class AuthManager {
  private listeners: Set<AuthListener> = new Set();

  /**
   * Subscribe to auth state changes (session expiry).
   * Returns unsubscribe function.
   */
  subscribe(listener: AuthListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /**
   * Signal that the session has expired (401 received).
   * Clears token and notifies all listeners.
   */
  signalSessionExpired(): void {
    sessionStorage.removeItem('dashboard_token');
    this.listeners.forEach((listener) => listener());
  }

  /**
   * Check if user is authenticated.
   */
  isAuthenticated(): boolean {
    return !!sessionStorage.getItem('dashboard_token');
  }

  /**
   * Get stored session token (if any).
   */
  getToken(): string | null {
    return sessionStorage.getItem('dashboard_token');
  }

  /**
   * Store session token after successful login.
   */
  setToken(token: string): void {
    sessionStorage.setItem('dashboard_token', token);
  }

  /**
   * Clear token (logout).
   */
  clearToken(): void {
    sessionStorage.removeItem('dashboard_token');
    this.listeners.forEach((listener) => listener());
  }
}

// Singleton instance
export const authManager = new AuthManager();
