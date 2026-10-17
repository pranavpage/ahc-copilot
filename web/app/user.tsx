"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";

// The user who is talking. Kept in localStorage and in the `copilot_user` cookie; the /api proxy
// sends the cookie to the LangGraph server as the `x-user-id` header, and the agent reads it.

export type User = { user_id: string; name: string; role: string; team_name: string | null };

const COOKIE = "copilot_user";
const STORAGE_KEY = "copilot_user";

type UserState = {
  users: User[];
  userId: string | null;
  user: User | undefined;
  setUserId: (id: string) => void;
};

const UserContext = createContext<UserState | null>(null);

function saveUser(id: string) {
  localStorage.setItem(STORAGE_KEY, id);
  document.cookie = `${COOKIE}=${encodeURIComponent(id)}; path=/; SameSite=Strict`;
}

export function UserProvider({ children }: { children: React.ReactNode }) {
  const [users, setUsers] = useState<User[]>([]);
  const [userId, setUserIdState] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/copilot/users")
      .then((r) => (r.ok ? r.json() : []))
      .then((list: User[]) => {
        setUsers(list);
        const saved = localStorage.getItem(STORAGE_KEY);
        const id = list.some((u) => u.user_id === saved) ? saved! : list[0]?.user_id;
        if (id) {
          saveUser(id);
          setUserIdState(id);
        }
      })
      .catch(() => setUsers([]));
  }, []);

  const setUserId = useCallback((id: string) => {
    saveUser(id);
    setUserIdState(id);
  }, []);

  const user = users.find((u) => u.user_id === userId);
  return (
    <UserContext.Provider value={{ users, userId, user, setUserId }}>
      {children}
    </UserContext.Provider>
  );
}

export function useUser(): UserState {
  const ctx = useContext(UserContext);
  if (!ctx) throw new Error("useUser needs a UserProvider");
  return ctx;
}

export function UserPicker() {
  const { users, userId, setUserId } = useUser();
  if (users.length === 0) return null;
  return (
    <label className="flex flex-col gap-1 px-2 py-2 text-xs text-muted-foreground">
      Talking as
      <select
        className="rounded-md border bg-background px-2 py-1.5 text-sm text-foreground"
        value={userId ?? ""}
        onChange={(e) => setUserId(e.target.value)}
      >
        {users.map((u) => (
          <option key={u.user_id} value={u.user_id}>
            {u.name} ({u.role.replaceAll("_", " ")})
          </option>
        ))}
      </select>
    </label>
  );
}
