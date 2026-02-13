/**
 * Auth state manager with cross-component session expiry signaling.
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
   * Clears password and notifies all listeners.
   */
  signalSessionExpired(): void {
    sessionStorage.removeItem('dashboard_password');
    this.listeners.forEach((listener) => listener());
  }

  /**
   * Check if user is authenticated.
   */
  isAuthenticated(): boolean {
    return !!sessionStorage.getItem('dashboard_password');
  }

  /**
   * Get stored password (if any).
   */
  getPassword(): string | null {
    return sessionStorage.getItem('dashboard_password');
  }

  /**
   * Store password after successful login.
   */
  setPassword(password: string): void {
    sessionStorage.setItem('dashboard_password', password);
  }

  /**
   * Clear password (logout).
   */
  clearPassword(): void {
    sessionStorage.removeItem('dashboard_password');
    this.listeners.forEach((listener) => listener());
  }
}

// Singleton instance
export const authManager = new AuthManager();
