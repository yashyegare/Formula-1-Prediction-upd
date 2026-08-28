import { useEffect } from 'react';
import { useSelector } from 'react-redux';
import { signIn, signUp, signOut, sendVerificationEmail } from '../lib/auth-client';
import { type RootState, useAppDispatch } from '../store';
import { setUser, setLoading, openAuthModal, closeAuthModal, logout } from '../store/slices/authSlice';

const API_BASE = import.meta.env.PUBLIC_API_BASE_URL || 'http://localhost:8000';

export function useAuth() {
  const dispatch = useAppDispatch();
  const { user, isLoading, isAuthenticated, showAuthModal, authModalMode } = useSelector(
    (state: RootState) => state.auth
  );

  // Check Flask session on mount
  useEffect(() => {
    dispatch(setLoading(true));
    fetch(`${API_BASE}/api/auth/me`, { credentials: 'include' })
      .then(res => res.ok ? res.json() : null)
      .then(data => {
        if (data?.user) {
          dispatch(setUser({
            id: data.user.id,
            email: data.user.email,
            name: data.user.displayName || data.user.username,
            image: data.user.avatarUrl ?? null,
            emailVerified: true,
          }));
        } else {
          dispatch(setUser(null));
        }
      })
      .catch(() => dispatch(setUser(null)))
      .finally(() => dispatch(setLoading(false)));
  }, [dispatch]);

  const refreshSession = () => {
    fetch(`${API_BASE}/api/auth/me`, { credentials: 'include' })
      .then(res => res.ok ? res.json() : null)
      .then(data => {
        if (data?.user) {
          dispatch(setUser({
            id: data.user.id,
            email: data.user.email,
            name: data.user.displayName || data.user.username,
            image: data.user.avatarUrl ?? null,
            emailVerified: true,
          }));
        }
      })
      .catch(() => {});
  };

  const handleSignIn = async (email: string, password: string) => {
    const result = await signIn.email({ email, password } as any);
    if ((result as any).error) {
      throw new Error((result as any).error.message || 'Login failed');
    }
    refreshSession();
    dispatch(closeAuthModal());
    return result;
  };

  const handleSignUp = async (email: string, password: string, name: string) => {
    const result = await signUp.email({ email, password, name } as any);
    if ((result as any).error) {
      throw new Error((result as any).error.message || 'Signup failed');
    }
    refreshSession();
    return { ...result, needsVerification: false };
  };

  const handleResendVerification = async (email: string) => {
    const result = await sendVerificationEmail({ email } as any);
    if ((result as any).error) {
      throw new Error((result as any).error.message || 'Failed');
    }
    return result;
  };

  const handleSignOut = async () => {
    await signOut();
    dispatch(logout());
  };

  const handleGoogleSignIn = async () => {
    // Google sign-in not supported with Flask backend
    throw new Error('Google sign-in is not available. Please use email/password.');
  };

  const openSignIn = () => dispatch(openAuthModal('signin'));
  const openSignUp = () => dispatch(openAuthModal('signup'));
  const closeModal = () => dispatch(closeAuthModal());

  return {
    user,
    isLoading,
    isAuthenticated,
    showAuthModal,
    authModalMode,
    signIn: handleSignIn,
    signUp: handleSignUp,
    signOut: handleSignOut,
    signInWithGoogle: handleGoogleSignIn,
    resendVerification: handleResendVerification,
    openSignIn,
    openSignUp,
    closeModal,
  };
}
