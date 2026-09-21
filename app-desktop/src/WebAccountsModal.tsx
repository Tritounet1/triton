import { Button } from "@astryxdesign/core/Button";
import { Dialog } from "@astryxdesign/core/Dialog";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { useEffect, useState, type SyntheticEvent } from "react";
import { API_BASE } from "./api";
import { XIcon } from "./icons";

interface WebAccount {
  id: string;
  username: string;
  role: "admin" | "member";
}

interface WebAccountsModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSignedOut: () => void;
}

export function WebAccountsModal({ isOpen, onClose, onSignedOut }: WebAccountsModalProps) {
  const [accounts, setAccounts] = useState<WebAccount[] | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<WebAccount["role"]>("member");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    void fetch(`${API_BASE}/accounts`, { credentials: "include" })
      .then(async (response) => {
        if (response.status === 403) return null;
        if (!response.ok) throw new Error("Impossible de charger les comptes.");
        return (await response.json()) as WebAccount[];
      })
      .then(setAccounts)
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "Impossible de charger les comptes.");
      });
  }, [isOpen]);

  async function createAccount(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/accounts`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password, role }),
      });
      if (!response.ok) {
        const detail = (await response.json().catch(() => null)) as { detail?: string } | null;
        throw new Error(detail?.detail ?? "Impossible de créer le compte.");
      }
      const account = (await response.json()) as WebAccount;
      setAccounts((current) => (current ? [...current, account] : current));
      setUsername("");
      setPassword("");
      setRole("member");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Impossible de créer le compte.");
    } finally {
      setSubmitting(false);
    }
  }

  async function signOut() {
    await fetch(`${API_BASE}/auth/logout`, { method: "POST", credentials: "include" });
    onSignedOut();
  }

  return (
    <Dialog
      isOpen={isOpen}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      purpose="info"
      width={520}
      aria-label="Compte web"
    >
      <div className="relative space-y-6 p-2">
        <IconButton
          label="Fermer"
          icon={<XIcon />}
          variant="ghost"
          size="sm"
          onClick={onClose}
          className="absolute right-0 top-0"
        />
        <div>
          <h2 className="m-0 text-lg font-semibold">Compte web</h2>
          <Text color="secondary" size="sm" className="mt-1 block">
            Gérez les accès à cette instance Triton.
          </Text>
        </div>
        {accounts === null ? (
          <Text color="secondary" size="sm">
            Seul un administrateur peut gérer les comptes.
          </Text>
        ) : (
          <>
            <div className="space-y-2">
              <Text size="sm" weight="medium">Comptes</Text>
              {accounts.map((account) => (
                <div
                  key={account.id}
                  className="flex items-center justify-between rounded-md border border-border px-3 py-2"
                >
                  <Text size="sm">{account.username}</Text>
                  <Text color="secondary" size="2xs">{account.role}</Text>
                </div>
              ))}
            </div>
            <form
              className="space-y-3 border-t border-border pt-5"
              onSubmit={(event) => {
                void createAccount(event);
              }}
            >
              <Text size="sm" weight="medium">Ajouter un compte</Text>
              <TextInput
                label="Identifiant"
                value={username}
                onChange={setUsername}
                isRequired
                isDisabled={submitting}
              />
              <TextInput
                label="Mot de passe"
                type="password"
                value={password}
                onChange={setPassword}
                isRequired
                isDisabled={submitting}
              />
              <label className="block text-sm font-medium text-primary">
                Rôle
                <select
                  className="mt-1.5 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm"
                  value={role}
                  onChange={(event) => {
                    setRole(event.target.value as WebAccount["role"]);
                  }}
                  disabled={submitting}
                >
                  <option value="member">Membre</option>
                  <option value="admin">Administrateur</option>
                </select>
              </label>
              <Button type="submit" isDisabled={submitting} label="Créer le compte">
                {submitting ? "Création…" : "Créer le compte"}
              </Button>
            </form>
          </>
        )}
        {error && <Text className="block text-red-500" size="sm">{error}</Text>}
        <div className="border-t border-border pt-4">
          <Button label="Se déconnecter" variant="secondary" onClick={() => { void signOut(); }}>
            Se déconnecter
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
