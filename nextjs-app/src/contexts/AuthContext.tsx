import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import {
  AuthUser,
  getCurrentUser as apiGetCurrentUser,
  signIn as apiSignIn,
  signUp as apiSignUp,
  signOut as apiSignOut,
} from "../lib/auth";

interface AuthContextType {
  user: AuthUser | null;
  loading: boolean;
  signIn: (username: string, password: string) => Promise<string | null>;
  signUp: (
    username: string,
    email: string,
    password: string,
    displayName?: string
  ) => Promise<string | null>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  loading: true,
  signIn: async () => null,
  signUp: async () => null,
  signOut: async () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  // Check session on mount
  useEffect(() => {
    apiGetCurrentUser().then((u) => {
      setUser(u);
      setLoading(false);
    });
  }, []);

  const signIn = useCallback(async (username: string, password: string) => {
    const res = await apiSignIn(username, password);
    if (res.error) return res.error;
    if (res.user) setUser(res.user);
    return null;
  }, []);

  const signUp = useCallback(
    async (username: string, email: string, password: string, displayName?: string) => {
      const res = await apiSignUp(username, email, password, displayName);
      if (res.error) return res.error;
      if (res.user) setUser(res.user);
      return null;
    },
    []
  );

  const signOut = useCallback(async () => {
    await apiSignOut();
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, signIn, signUp, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
