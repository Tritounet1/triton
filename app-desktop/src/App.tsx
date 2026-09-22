import { AlertDialog } from "@astryxdesign/core/AlertDialog";
import { AppShell } from "@astryxdesign/core/AppShell";
import { Avatar } from "@astryxdesign/core/Avatar";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import {
  ChatComposer,
  ChatComposerDrawer,
  ChatComposerInput,
  ChatLayout,
  ChatLayoutScrollButton,
  ChatMessage,
  ChatMessageBubble,
  ChatMessageList,
  ChatMessageMetadata,
  ChatSystemMessage,
  ChatToolCalls,
  type ChatComposerToken,
  type ChatComposerTrigger,
} from "@astryxdesign/core/Chat";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Markdown } from "@astryxdesign/core/Markdown";
import { SideNav } from "@astryxdesign/core/SideNav";
import { Spinner } from "@astryxdesign/core/Spinner";
import { Text } from "@astryxdesign/core/Text";
import { Theme } from "@astryxdesign/core/theme";
import { Timestamp } from "@astryxdesign/core/Timestamp";
import {
  createStaticSource,
  type SearchableItem,
} from "@astryxdesign/core/Typeahead";
import { neutralTheme } from "@astryxdesign/theme-neutral/built";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import "./App.css";
import { API_BASE, isWebDeployment } from "./api";
import { BackgroundTasksPanel } from "./BackgroundTasksPanel";
import { type BackgroundTask } from "./BackgroundTasksSection";
import {
  COMPACT_COMMAND,
  COST_COMMAND,
  createChatCommands,
  MODEL_COMMAND_PREFIX,
  MULTI_AGENT_PREFIX,
  REMEMBER_PREFIX,
  UNDO_COMMAND,
  YOLO_COMMAND,
} from "./chatCommands";
import { ConversationSidebarSection } from "./ConversationSidebarSection";
import {
  runChatConversationStream,
  type PendingConfirmation,
} from "./chatConversationStream";
import { DesktopTitlebar } from "./DesktopTitlebar";
import {
  assistantGroupModel,
  editFileTarget,
  formatSessionLabel,
  groupMessages,
  historyToMessages,
  isPdfDataUrl,
  parseEditFileEdits,
  parseToolDisplay,
  stripWebSearchSource,
  toBlocks,
  toolCallStatus,
  toolDiffStats,
  truncateBeforeTurn,
  userMessageAtTurn,
  webSearchSource,
  type ChatMsg,
  type EditFileEdit,
  type RawSessionMessage,
  type ToolCallLike,
  type ToolMsg,
} from "./chatMessages";
import { type OpenFile } from "./fileViewer";
import { FileViewerPanel } from "./FileViewerPanel";
import { formatArgs } from "./format";
import { ImagePreviewDialog } from "./ImagePreviewDialog";
import {
  CheckIcon,
  ChevronRightIcon,
  CopyIcon,
  FileIcon,
  GearIcon,
  ImageIcon,
  MoonIcon,
  PencilIcon,
  PlusIcon,
  RefreshIcon,
  SunIcon,
  XIcon,
} from "./icons";
import { modelAvatar } from "./modelFamilies";
import { NewProjectModal } from "./NewProjectModal";
import { notifyIfBackground } from "./notifications";
import { ProjectFilePanel } from "./ProjectFilePanel";
import { ProjectSidebarSection } from "./ProjectSidebarSection";
import { RichCard } from "./RichCard";
import { richCardFromToolCall } from "./richCardData";
import { SearchPage } from "./SearchPage";
import { SettingsModal } from "./SettingsModal";
import { SidebarHeader } from "./SidebarHeader";
import {
  describeSnapshotDiff,
  type SnapshotDiff,
  type SnapshotPoint,
} from "./snapshotDiff";
import { SnapshotHistoryView } from "./SnapshotHistoryView";
import { SubagentsPanel } from "./SubagentsPanel";
import { TaskView } from "./TaskView";

// au dela de ce delai sans le moindre evenement SSE, on considere qu'on
// est dans un "silence" (ex. un outil qui tourne cote serveur) plutot que
// dans un flux de tokens actif - voir awaitingSseEvent. Assez court pour
// rester reactif, assez long pour ne jamais se declencher entre deux
// tokens d'un flux de texte normal (qui arrivent bien plus vite que ca).
const SSE_IDLE_MS = 500;
// distance (px) par rapport au bas du fil de discussion au-dela de laquelle
// le bouton "revenir en bas" s'affiche - voir showScrollButton.
const SCROLL_BUTTON_THRESHOLD_PX = 100;
// doit rester alignee avec MAX_ATTACHMENT_BYTES cote serveur (server.py) :
// une image plus grande est rejetee ici avant meme d'etre envoyee.
const MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024;
// un fichier texte n'est jamais envoye comme piece jointe binaire (voir
// PendingTextAttachment plus bas) : son contenu est colle tel quel dans le
// texte du message a l'envoi, donc dans le contexte du modele - une limite
// bien plus basse que celle des images/PDF est necessaire.
const MAX_TEXT_ATTACHMENT_BYTES = 200 * 1024;
const TEXT_ATTACHMENT_EXTENSIONS = [
  ".txt",
  ".md",
  ".markdown",
  ".csv",
  ".json",
  ".log",
  ".yaml",
  ".yml",
];
// menu declenche par "/" dans le composer (style Notion/Discord), via le
// mecanisme de trigger deja fourni par ChatComposerInput.
const SLASH_COMMANDS: SearchableItem<{ description: string }>[] = [
  {
    id: "multi-agents",
    label: "multi-agents",
    auxiliaryData: {
      description:
        "Répartit la tâche entre plusieurs agents spécialisés (recherche, code, rédaction...)",
    },
  },
  {
    id: "model",
    label: "model",
    auxiliaryData: {
      description: "Change le modèle de cette conversation (ex. /model gpt-5)",
    },
  },
  {
    id: "cost",
    label: "cost",
    auxiliaryData: {
      description:
        "Affiche le coût et les tokens utilisés dans cette conversation",
    },
  },
  {
    id: "undo",
    label: "undo",
    auxiliaryData: {
      description:
        "Restaure le dossier du projet à l'état d'avant cette session (filet de sécurité)",
    },
  },
  {
    id: "remember-session",
    label: "remember session",
    auxiliaryData: {
      description:
        "Note quelque chose pour cette conversation (ou son projet, si elle en a un)",
    },
  },
  {
    id: "remember-global",
    label: "remember global",
    auxiliaryData: {
      description:
        "Note quelque chose dans la mémoire globale, partagée par toutes les conversations",
    },
  },
  {
    id: "compact",
    label: "compact",
    auxiliaryData: {
      description:
        "Résume les échanges les plus anciens dès maintenant, sans attendre que le contexte soit plein",
    },
  },
  {
    id: "yolo",
    label: "yolo",
    auxiliaryData: {
      description:
        "Active/désactive le mode YOLO pour cette conversation : plus de demande d'autorisation avant une action (écriture, commande...)",
    },
  },
];

const slashCommandSource = createStaticSource(SLASH_COMMANDS);

const composerTriggers: ChatComposerTrigger[] = [
  {
    character: "/",
    searchSource: slashCommandSource,
    menuLabel: "Commandes",
    emptySearchResultsText: "Aucune commande",
    // un jeton (puce) plutot qu'un texte brut : la commande se distingue
    // visuellement de ce qui suit (le texte tape ensuite reste normal,
    // hors du jeton) - `value` est ce qui finit dans le message envoye,
    // identique a l'ancien texte brut inséré, donc le parsing de
    // sendMessage (prefixes /model, /remember session, etc.) ne change pas.
    onSelect: (item): ChatComposerToken => ({
      value: `/${item.label} `,
      label: `/${item.label}`,
      variant: "neutral",
    }),
    renderItem: (item) => {
      const description = (item as SearchableItem<{ description: string }>)
        .auxiliaryData?.description;
      return (
        <div className="flex flex-col gap-0.5 px-2 py-1.5">
          <Text size="sm" weight="medium">
            /{item.label}
          </Text>
          {description && (
            <Text size="2xs" color="secondary">
              {description}
            </Text>
          )}
        </div>
      );
    },
  },
];

interface PendingAttachment {
  name: string;
  dataUrl: string;
}

/** Fichier texte (txt/md/csv/json/...) en attente d'envoi : contrairement a
 * PendingAttachment (image/PDF), jamais transmis en piece jointe binaire au
 * serveur - son contenu est colle directement dans le texte du message a
 * l'envoi (voir sendMessage), donc lisible par n'importe quel modele sans
 * exiger de modalite "vision"/"file". */
interface PendingTextAttachment {
  name: string;
  content: string;
}

interface Session {
  id: string;
  title: string | null;
  project_id: string | null;
  pinned: boolean;
}

interface Project {
  id: string;
  name: string;
  folder_path: string;
}

/** Avant/apres pour un edit_file : construit a partir des arguments de
 * l'appel (old_string/new_string), pas du resultat (juste un message de
 * confirmation) - pas de diff ligne a ligne fine, juste tout l'ancien bloc
 * en rouge puis tout le nouveau en vert, largement suffisant pour voir ce
 * qui a change d'un coup d'oeil. */
function EditFileDiff({
  oldString,
  newString,
}: {
  oldString: string;
  newString: string;
}) {
  return (
    <div className="max-h-64 overflow-y-auto rounded-lg font-mono text-xs">
      {oldString !== "" &&
        oldString.split("\n").map((line, i) => (
          <div
            key={`old-${i}`}
            className="whitespace-pre bg-error-muted px-2 py-0.5 text-error"
          >
            <span className="select-none opacity-60">- </span>
            {line}
          </div>
        ))}
      {newString !== "" &&
        newString.split("\n").map((line, i) => (
          <div
            key={`new-${i}`}
            className="whitespace-pre bg-success-muted px-2 py-0.5 text-success"
          >
            <span className="select-none opacity-60">+ </span>
            {line}
          </div>
        ))}
    </div>
  );
}

/** Meme rendu que EditFileDiff (tout l'ancien bloc en rouge, tout le
 * nouveau en vert), mais pour un write_file : "l'ancien" n'est pas dans
 * les arguments de l'appel (juste `content`, le nouveau contenu), donc on
 * va chercher l'etat actuel du fichier via l'endpoint deja utilise par le
 * visualiseur de fichiers (voir FileViewerPanel.tsx) - un fichier
 * inexistant (404, nouvelle creation) n'affiche alors que le bloc vert. */
function WriteFileDiff({
  projectId,
  path,
  newContent,
}: {
  projectId: string;
  path: string;
  newContent: string;
}) {
  const [oldContent, setOldContent] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  // pas de reset synchrone de `loaded` ici (interdit dans un effet - voir
  // McpSettings.tsx pour le meme garde-fou) : chaque confirmation write_file
  // est sequentielle (pendingConfirmation repasse par null entre deux),
  // donc ce composant remonte a chaque fois plutot que de reutiliser son
  // etat entre deux appels differents.
  useEffect(() => {
    fetch(
      `${API_BASE}/projects/${projectId}/file?path=${encodeURIComponent(path)}`,
    )
      .then((r) => (r.ok ? r.text() : null))
      .then((text) => {
        setOldContent(text);
      })
      .catch(() => {
        setOldContent(null);
      })
      .finally(() => {
        setLoaded(true);
      });
  }, [projectId, path]);

  if (!loaded) {
    return (
      <Spinner
        size="sm"
        shade="subtle"
        aria-label="Chargement du contenu actuel"
      />
    );
  }

  return <EditFileDiff oldString={oldContent ?? ""} newString={newContent} />;
}

/** Un EditFileDiff par hunk, groupes par fichier (avec le chemin en
 * en-tete des qu'il y en a plus d'un) - le rendu "detail" complet d'un
 * appel edit_file, que ce soit pour la preview de confirmation ou pour
 * l'historique deja execute. */
function EditFileEdits({ edits }: { edits: EditFileEdit[] }) {
  const byPath = new Map<string, EditFileEdit[]>();
  for (const e of edits) {
    const list = byPath.get(e.path) ?? [];
    list.push(e);
    byPath.set(e.path, list);
  }
  return (
    <div className="flex flex-col gap-3">
      {[...byPath.entries()].map(([path, hunks]) => (
        <div key={path} className="flex flex-col gap-1">
          {byPath.size > 1 && (
            <Text size="2xs" color="secondary" className="font-mono">
              {path}
            </Text>
          )}
          {hunks.map((h, i) => (
            <EditFileDiff
              key={i}
              oldString={h.old_string}
              newString={h.new_string}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

function toolResultDetail(t: ToolCallLike): ReactNode {
  if (t.tool === "edit_file") {
    const edits = parseEditFileEdits(t.args);
    if (edits.length > 0) return <EditFileEdits edits={edits} />;
  }
  const { content } = t.args;
  if (t.tool === "write_file" && typeof content === "string") {
    // pas d'"avant" fiable a afficher ici (contrairement a la preview de
    // confirmation - voir WriteFileDiff plus haut, qui va chercher l'etat
    // *actuel* du fichier) : cet appel appartient a l'historique, un
    // fetch "maintenant" ne refleterait son etat juste avant CET appel que
    // si rien ne l'a modifie depuis - pas garanti. Le nouveau contenu
    // ecrit, lui, est un fait connu avec certitude (l'argument de l'appel).
    return <EditFileDiff oldString="" newString={content} />;
  }
  const result =
    t.tool === "web_search" ? stripWebSearchSource(t.result) : t.result;
  return (
    <pre className="max-h-48 overflow-y-auto whitespace-pre-wrap text-xs">
      {result}
    </pre>
  );
}

/** Detail d'une sous-tache multi-agent : sa description, puis ses propres
 * appels d'outils (meme composant ChatToolCalls, imbrique) mis a jour en
 * direct pendant qu'elle tourne, et enfin son resultat une fois conclue. */
function multiAgentSubtaskDetail(t: ToolMsg): ReactNode {
  const calls = t.subtaskToolCalls ?? [];
  return (
    <div className="flex flex-col gap-2">
      {t.subtaskDescription && (
        <p className="text-xs text-secondary">{t.subtaskDescription}</p>
      )}
      {calls.length > 0 && (
        <ChatToolCalls
          defaultIsExpanded
          calls={calls.map((c) => ({
            name: c.tool,
            status: toolCallStatus(c.result),
            node:
              c.tool === "web_search" ? webSearchSource(c.result) : undefined,
            target:
              c.tool === "edit_file"
                ? editFileTarget(c.args)
                : formatArgs(c.args),
            ...toolDiffStats(c),
            resultDetail: toolResultDetail(c),
          }))}
        />
      )}
      {t.result && (
        <pre className="max-h-48 overflow-y-auto whitespace-pre-wrap text-xs">
          {t.result}
        </pre>
      )}
    </div>
  );
}

function App() {
  // Sous macOS/Tauri, la fenetre utilise une titlebar « Overlay ». Ce test
  // conserve la barre native habituelle dans le navigateur de developpement
  // et sur les autres plateformes, tout en laissant de la place aux boutons
  // rouge/jaune/vert dans l'application desktop.
  const usesMacTitlebarOverlay =
    typeof window !== "undefined" &&
    "__TAURI_INTERNALS__" in window &&
    navigator.userAgent.includes("Mac");
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  // ids des conversations avec un envoi en cours ("" pour une toute
  // nouvelle conversation pas encore identifiee par le serveur - voir
  // sendMessage) - permet de changer de conversation pendant qu'une
  // reponse arrive en streaming (comme ChatGPT/Claude) sans que ca la
  // bloque : chaque sendMessage() suit son propre envoi independamment de
  // celle affichee a l'ecran. `sending` (defini plus bas, une fois
  // sessionId disponible ; utilise partout ailleurs dans l'UI) ne reflete
  // que celui de la conversation actuellement affichee.
  const [sendingSessionIds, setSendingSessionIds] = useState<Set<string>>(
    () => new Set(),
  );
  // Modele associe a une requete encore en cours. Il peut differer du
  // modele de chat par defaut, par exemple pour une image Gemini ponctuelle.
  const [inFlightModels, setInFlightModels] = useState<Record<string, string>>(
    {},
  );
  // vrai des qu'aucun evenement SSE n'est arrive depuis SSE_IDLE_MS pour la
  // conversation affichee - couvre le "silence" pendant qu'un outil tourne
  // cote serveur juste apres un morceau de texte assistant (ex. "Je vais
  // ecrire le fichier X." suivi d'un write_file qui prend plusieurs
  // secondes) : showTypingPlaceholder masquait le loader des qu'un texte
  // assistant etait deja affiche, meme si plus rien n'arrivait ensuite -
  // voir sendMessage's noteSseEvent, appele a chaque evenement recu.
  const [awaitingSseEvent, setAwaitingSseEvent] = useState(false);
  const [apiModel, setApiModel] = useState<string | null>(null);
  // Equivalent du modele de chat par defaut, mais specifique a l'endpoint
  // Images. Les deux reglages restent totalement independants.
  const [imageModel, setImageModel] = useState<string | null>(null);
  const [oneShotChatModel, setOneShotChatModel] = useState<string | null>(null);
  const [oneShotImageModel, setOneShotImageModel] = useState<string | null>(null);
  const [imageMode, setImageMode] = useState(false);
  const [previewImage, setPreviewImage] = useState<string | null>(null);
  // modele propre a la conversation en cours, mis via la commande /model
  // (PUT /sessions/{id}/model) - prend le pas sur apiModel (le defaut
  // global) tant qu'il est defini. null = pas de surcharge, la conversation
  // suit le modele global comme avant l'existence de cette commande.
  const [sessionModelOverride, setSessionModelOverride] = useState<
    string | null
  >(null);
  // /yolo pour CETTE conversation (voir GET/POST /sessions/{id}/yolo) :
  // affiche un bandeau persistant tant qu'actif (pas juste un toast au
  // moment du bascule), puisque ca change silencieusement ce que fait
  // chaque message suivant.
  const [yoloEnabled, setYoloEnabled] = useState(false);
  // catalogue OpenRouter (id + capacites), recupere une fois au demarrage,
  // pour savoir si le modele actuel accepte des images et/ou des PDF
  // (active/desactive et filtre le bouton "joindre" du composer) sans
  // dupliquer cette logique cote serveur.
  const [modelsCatalog, setModelsCatalog] = useState<
    {
      id: string;
      name: string;
      supports_images: boolean;
      supports_files: boolean;
    }[]
  >([]);
  const [imageModelsCatalog, setImageModelsCatalog] = useState<
    { id: string; name: string; description: string }[]
  >([]);
  const [pendingAttachments, setPendingAttachments] = useState<
    PendingAttachment[]
  >([]);
  const [pendingTextAttachments, setPendingTextAttachments] = useState<
    PendingTextAttachment[]
  >([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // compteur plutot qu'un booleen simple : dragenter/dragleave se
  // declenchent aussi en survolant les enfants (la liste de messages, le
  // composer...), donc un simple "entree = true / sortie = false" clignote
  // des qu'on traverse une frontiere d'enfant a l'interieur meme de la
  // zone de drop. Le compteur ne retombe a 0 (masque l'overlay) qu'une
  // fois vraiment sorti de tous les enfants imbriques.
  const [dragDepth, setDragDepth] = useState(0);
  const [sessionId, setSessionId] = useState<string | null>(() =>
    localStorage.getItem("triton_session_id"),
  );
  const sending = sendingSessionIds.has(sessionId ?? "");
  const [sessions, setSessions] = useState<Session[]>([]);
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingValue, setEditingValue] = useState("");
  const [editingProjectId, setEditingProjectId] = useState<string | null>(null);
  const [editingProjectValue, setEditingProjectValue] = useState("");
  const [deletingSession, setDeletingSession] = useState<Session | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [remoteProjectsEnabled, setRemoteProjectsEnabled] = useState(!isWebDeployment);
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null);
  const [showProjectForm, setShowProjectForm] = useState(false);
  const [deletingProject, setDeletingProject] = useState<Project | null>(null);
  // confirmation pour la commande /undo (voir handleUndoCommand) - meme
  // AlertDialog que les suppressions ci-dessus, action destructrice donc
  // pas de raccourci sans confirmation meme depuis le composer. /undo
  // cible toujours le point de restauration le plus recent (annuler le
  // dernier message) - "annuler toute la session" reste une action du
  // panneau fichiers (SnapshotSection.tsx), pas de la commande texte.
  const [undoTarget, setUndoTarget] = useState<SnapshotPoint | null>(null);
  const [undoing, setUndoing] = useState(false);
  // meme diff que SnapshotSection.tsx pour la meme confirmation - chargee
  // des l'ouverture, pas au montage (voir snapshotDiff.ts).
  const [undoDiff, setUndoDiff] = useState<SnapshotDiff | null>(null);
  const [collapsedProjectIds, setCollapsedProjectIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [fileRefreshTick, setFileRefreshTick] = useState(0);
  // fichier ouvert dans le visualiseur (PDF/HTML/Markdown) : remplace
  // ProjectFilePanel dans le meme emplacement tant qu'il est ouvert (voir
  // FileViewerPanel.tsx).
  const [openFile, setOpenFile] = useState<OpenFile | null>(null);
  // sidebar repliable a la Claude desktop : repliee, elle disparait
  // entierement (pas un simple rail d'icones) ; passer la souris sur le
  // bord gauche la montre en survol temporaire (sidebarPeeking), il faut
  // cliquer le bouton pour l'epingler ouverte pour de bon.
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => localStorage.getItem("triton_sidebar_collapsed") === "1",
  );
  const [sidebarPeeking, setSidebarPeeking] = useState(false);
  const toggleSidebar = () => {
    const next = !sidebarCollapsed;
    setSidebarCollapsed(next);
    setSidebarPeeking(false);
    localStorage.setItem("triton_sidebar_collapsed", next ? "1" : "0");
  };
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  // turnIndex (1-based, voir groupMessages) du message utilisateur en cours
  // d'edition, null si aucun - un seul a la fois, edite en place dans sa
  // propre bulle (voir le rendu du groupe "user" plus bas).
  const [editingTurnIndex, setEditingTurnIndex] = useState<number | null>(null);
  const [editingText, setEditingText] = useState("");
  const [pendingConfirmation, setPendingConfirmation] =
    useState<PendingConfirmation | null>(null);
  // repliee par defaut (style Claude Desktop) - args/diff caches jusqu'a
  // ce qu'on clique pour les voir.
  const [confirmationDetailsExpanded, setConfirmationDetailsExpanded] =
    useState(false);
  // remise a false a chaque nouvelle confirmation (id different - y
  // compris en revenant sur une conversation qui en avait une en attente,
  // voir switchSession) : ajustement synchrone pendant le rendu (pattern
  // React officiel "adjusting state when a prop changes"), pas dans un
  // effet - react-hooks/set-state-in-effect l'interdirait sinon.
  const [lastConfirmationId, setLastConfirmationId] = useState<string | null>(
    null,
  );
  if ((pendingConfirmation?.id ?? null) !== lastConfirmationId) {
    setLastConfirmationId(pendingConfirmation?.id ?? null);
    setConfirmationDetailsExpanded(false);
  }
  // un AbortController/une confirmation en attente par conversation (cle :
  // sessionId, ou "" pour une toute nouvelle pas encore identifiee - meme
  // convention que sendingSessionIds) plutot qu'une seule valeur globale :
  // sendMessage() pour une conversation qui n'est plus affichee doit
  // rester annulable/repondable une fois qu'on y revient, sans se faire
  // ecraser par l'envoi d'une autre conversation entre-temps. Des refs
  // (pas du state) : rien ici n'a besoin de re-rendu tant que la
  // conversation en question n'est pas celle affichee - voir sendMessage/
  // cancelMessage/respondToConfirmation.
  const abortControllersRef = useRef<Map<string, AbortController>>(new Map());
  const pendingConfirmationsRef = useRef<Map<string, PendingConfirmation>>(
    new Map(),
  );
  // minuteur du "silence SSE" (voir awaitingSseEvent) - une seule
  // conversation affichee a la fois, donc pas besoin d'une Map par session
  // comme les refs juste au-dessus.
  const sseIdleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // bouton "revenir en bas" du fil de discussion - remplace celui fourni
  // par defaut par ChatLayout (scrollButton), dont le "nouveaux messages"
  // reste affiche tant qu'on ne clique pas dessus meme apres etre revenu
  // en bas au trackpad/molette (sa propre logique ne le reinitialise que
  // via un dismiss() explicite). Ici, visible/label ne dependent que de la
  // position de scroll actuelle - plus aucun etat "bloque".
  const chatScrollRef = useRef<HTMLDivElement>(null);
  const [showScrollButton, setShowScrollButton] = useState(false);
  const [hasNewMessage, setHasNewMessage] = useState(false);

  useEffect(() => {
    const el = chatScrollRef.current;
    if (!el) return;
    function onScroll() {
      if (!el) return;
      const distanceFromBottom =
        el.scrollHeight - el.scrollTop - el.clientHeight;
      const scrolledUp = distanceFromBottom > SCROLL_BUTTON_THRESHOLD_PX;
      setShowScrollButton(scrolledUp);
      if (!scrolledUp) setHasNewMessage(false);
    }
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      el.removeEventListener("scroll", onScroll);
    };
  }, [sessionId]);

  // signale "nouveaux messages" uniquement si un message vient de
  // s'ajouter (pas juste du texte qui continue de s'accumuler dans le
  // dernier, voir scheduleFlush dans sendMessage) pendant qu'on est deja
  // scrolle plus haut - inutile de le signaler si on est deja en bas, le
  // scroll-suiveur de ChatLayout nous y garde de toute facon. Ajustement
  // pendant le rendu (pas dans un effet - interdit d'y appeler setState
  // synchrone, voir McpSettings.tsx pour le meme garde-fou) : compare a
  // la derniere longueur vue, meme mecanisme que lastConfirmationId plus
  // haut pour confirmationDetailsExpanded.
  const [lastMessagesLength, setLastMessagesLength] = useState(messages.length);
  if (messages.length !== lastMessagesLength) {
    setLastMessagesLength(messages.length);
    if (showScrollButton) setHasNewMessage(true);
  }
  // ids des sous-agents dispatches dans la conversation ACTIVE (remis a
  // zero au changement de conversation) : permet de relancer le modele
  // automatiquement une fois l'un d'eux termine, plutot que de rester en
  // attente indefiniment d'un nouveau message de l'utilisateur.
  const pendingSubagentIdsRef = useRef<Set<string>>(new Set());
  // tenues a jour apres chaque rendu (effet sans tableau de dependances),
  // lues depuis un minuteur autonome (setInterval) plutot qu'une fermeture
  // figee sur le rendu ou l'effet a demarre : evite de redemarrer ce
  // minuteur a chaque frappe/changement d'etat, cf. cancelMessage/
  // useCallback plus haut pour le meme probleme. Mutation directe pendant
  // le rendu interdite par react-hooks/refs, d'ou l'effet.
  const sendingRef = useRef(sending);
  const inputRef = useRef(input);
  // conversation actuellement affichee, lue par un sendMessage() en cours
  // (potentiellement pour une AUTRE conversation, lancee avant qu'on s'en
  // eloigne) pour savoir a chaque evenement SSE recu si son propre
  // session_id correspond encore a ce qui est affiche - sinon il continue
  // de tourner en fond, sans toucher `messages` (voir sendMessage). Une
  // ref plutot qu'un simple acces a `sessionId` : la fermeture d'un
  // sendMessage deja lance a capture sa propre valeur figee de sessionId,
  // celle-ci reste a jour meme apres qu'on ait navigue ailleurs.
  const displayedSessionIdRef = useRef(sessionId);
  const sendMessageRef = useRef((_text: string): void => undefined);
  useEffect(() => {
    sendingRef.current = sending;
    inputRef.current = input;
    displayedSessionIdRef.current = sessionId;
  });
  const [themeMode, setThemeMode] = useState<"light" | "dark">(() =>
    localStorage.getItem("triton_theme") === "light" ? "light" : "dark",
  );
  const [view, setView] = useState<
    "chat" | "task" | "search" | "snapshot_history"
  >("chat");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [backgroundTasks, setBackgroundTasks] = useState<BackgroundTask[]>([]);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);

  function toggleTheme() {
    setThemeMode((prev) => {
      const next = prev === "dark" ? "light" : "dark";
      localStorage.setItem("triton_theme", next);
      return next;
    });
  }

  function refreshApiModel() {
    fetch(`${API_BASE}/health`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data: { ok: boolean; model: string } | null) => {
        setApiModel(data?.model ?? null);
      })
      .catch(() => {
        setApiModel(null);
      });
  }

  function refreshImageModel() {
    fetch(`${API_BASE}/settings/image_model`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data: { model: string } | null) => {
        setImageModel(data?.model ?? null);
      })
      .catch(() => {
        setImageModel(null);
      });
  }

  // renvoie la liste chargee (en plus de mettre a jour l'etat) pour que le
  // montage initial puisse en retirer le project_id de la session restauree
  // depuis localStorage (voir l'effet ci-dessous) - un simple `setSessions`
  // ne suffit pas la, cet etat ne serait pas encore visible dans la meme
  // passe de useEffect.
  function loadSessions(): Promise<Session[]> {
    return fetch(`${API_BASE}/sessions`)
      .then((r) => (r.ok ? r.json() : []))
      .then((list: Session[]) => {
        const reversed = [...list].reverse();
        setSessions(reversed);
        return reversed;
      })
      .catch(() => {
        // API hors ligne ou requete echouee : la sidebar reste vide, sans casser l'app
        return [];
      });
  }

  function loadProjects() {
    fetch(`${API_BASE}/projects`)
      .then((r) => (r.ok ? r.json() : []))
      .then((list: Project[]) => {
        setProjects(list);
      })
      .catch(() => {
        // API hors ligne ou requete echouee : la liste de projets reste vide
      });
  }

  async function confirmDeleteProject() {
    if (!deletingProject) return;
    const id = deletingProject.id;
    setDeletingProject(null);

    const res = await fetch(`${API_BASE}/projects/${id}`, { method: "DELETE" });
    if (res.ok) {
      setProjects((await res.json()) as Project[]);
      if (activeProjectId === id) setActiveProjectId(null);
      void loadSessions();
    }
  }

  function startRename(session: Session) {
    setEditingSessionId(session.id);
    setEditingValue(session.title ?? formatSessionLabel(session.id));
  }

  async function commitRename(id: string) {
    const title = editingValue.trim();
    setEditingSessionId(null);
    if (!title) return;

    await fetch(`${API_BASE}/sessions/${id}/title`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, title } : s)));
  }

  async function togglePin(session: Session) {
    const pinned = !session.pinned;
    // optimiste : la sidebar re-trie immediatement, pas d'attente du
    // round-trip pour un simple booleen peu risque de rater
    setSessions((prev) =>
      prev.map((s) => (s.id === session.id ? { ...s, pinned } : s)),
    );
    await fetch(`${API_BASE}/sessions/${session.id}/pin`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pinned }),
    });
  }

  function startRenameProject(project: Project) {
    setEditingProjectId(project.id);
    setEditingProjectValue(project.name);
  }

  async function commitRenameProject(id: string) {
    const name = editingProjectValue.trim();
    setEditingProjectId(null);
    if (!name) return;

    const res = await fetch(`${API_BASE}/projects/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    if (res.ok) setProjects((await res.json()) as Project[]);
  }

  async function confirmDeleteSession() {
    if (!deletingSession) return;
    setIsDeleting(true);

    try {
      await fetch(`${API_BASE}/sessions/${deletingSession.id}`, {
        method: "DELETE",
      });
      setSessions((prev) => prev.filter((s) => s.id !== deletingSession.id));
      if (deletingSession.id === sessionId) {
        startNewSession();
      }
    } finally {
      setIsDeleting(false);
      setDeletingSession(null);
    }
  }

  function loadHistory(id: string) {
    fetch(`${API_BASE}/sessions/${id}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((raw: RawSessionMessage[] | null) => {
        if (raw) setMessages(historyToMessages(raw));
      })
      .catch(() => {
        // session introuvable cote serveur : on garde l'historique local tel quel
      });
  }

  useEffect(() => {
    refreshApiModel();
    refreshImageModel();

    fetch(`${API_BASE}/openrouter/models`)
      .then((r) => (r.ok ? r.json() : []))
      .then(
        (
          data: {
            id: string;
            name: string;
            supports_images: boolean;
            supports_files: boolean;
          }[],
        ) => {
          setModelsCatalog(data);
        },
      )
      .catch(() => {
        // API OpenRouter injoignable : le bouton "joindre" reste desactive
      });

    fetch(`${API_BASE}/openrouter/image-models`)
      .then((r) => (r.ok ? r.json() : []))
      .then((data: { id: string; name: string; description: string }[]) => {
        setImageModelsCatalog(data);
      })
      .catch(() => {
        // Le mode image reste present, mais le selecteur conserve alors le
        // modele par defaut configure plutot qu'une liste obsolète.
      });

    // uniquement au demarrage, pour une session deja connue (localStorage) ;
    // ne doit pas se redeclencher quand sendMessage() fixe sessionId lui-meme,
    // sinon ca part en course avec le streaming en cours.
    const stored = localStorage.getItem("triton_session_id");
    if (stored) loadHistory(stored);

    // switchSession() derive normalement activeProjectId de la liste des
    // sessions deja chargee en memoire, mais au demarrage la session
    // restauree ne passe pas par switchSession - sans ceci, le panneau du
    // dossier du projet reste invisible tant qu'on n'a pas change de
    // conversation puis qu'on n'y revient (bug signale par l'utilisateur).
    void loadSessions().then((list) => {
      if (stored)
        setActiveProjectId(
          list.find((s) => s.id === stored)?.project_id ?? null,
        );
    });
    if (!isWebDeployment) {
      loadProjects();
      return;
    }
    fetch(`${API_BASE}/deployment/capabilities`)
      .then((r) => (r.ok ? r.json() : { remote_workspaces: false }))
      .then((data: { remote_workspaces: boolean }) => {
        setRemoteProjectsEnabled(data.remote_workspaces);
        if (data.remote_workspaces) loadProjects();
      })
      .catch(() => {
        setRemoteProjectsEnabled(false);
      });
  }, []);

  // relance automatiquement le modele une fois qu'un sous-agent dispatche
  // dans la conversation active se termine : sans ca, le tour se termine
  // des que le modele repond en texte (pas d'appel d'outil) et plus rien ne
  // le fait revenir verifier le resultat tant que l'utilisateur n'envoie
  // pas un nouveau message. Lit sending/input via des refs (tenues a jour
  // a chaque rendu plus haut) plutot que de redemarrer ce minuteur a chaque
  // frappe/etat.
  useEffect(() => {
    const interval = setInterval(() => {
      if (pendingSubagentIdsRef.current.size === 0) return;
      if (sendingRef.current || inputRef.current.trim()) return;

      fetch(`${API_BASE}/subagents`)
        .then((r) => (r.ok ? r.json() : []))
        .then((data: { id: string; task: string; status: string }[]) => {
          const finished = data.find(
            (t) =>
              pendingSubagentIdsRef.current.has(t.id) && t.status !== "running",
          );
          if (!finished) return;
          pendingSubagentIdsRef.current.delete(finished.id);
          notifyIfBackground("Sous-agent terminé", finished.task);
          sendMessageRef.current(
            `(vérification automatique) Le sous-agent ${finished.id} a terminé, ` +
              "regarde son résultat avec check_subagent et continue la tâche.",
          );
        })
        .catch(() => {
          // API hors ligne : nouvelle tentative au prochain intervalle
        });
    }, 4000);
    return () => {
      clearInterval(interval);
    };
  }, []);

  // taches en arriere-plan (start_background_task) de la conversation
  // active : affichees dans le panneau lateral droit (BackgroundTasksPanel /
  // ProjectFilePanel), quel que soit le view courant, pour rester "vite
  // accessibles" pendant que le modele travaille dans la conversation.
  useEffect(() => {
    if (isWebDeployment || !sessionId) return;
    let cancelled = false;
    function load() {
      fetch(`${API_BASE}/background_tasks?session_id=${sessionId}`)
        .then((r) => (r.ok ? r.json() : []))
        .then((data: BackgroundTask[]) => {
          if (!cancelled) setBackgroundTasks(data);
        })
        .catch(() => {
          // API hors ligne : nouvelle tentative au prochain intervalle
        });
    }
    load();
    const interval = setInterval(load, 3000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [sessionId]);

  // surcharge de modele de la conversation en cours (voir /model) : pas de
  // reset synchrone a null ici (interdit dans un effet - voir
  // McpSettings.tsx pour le meme garde-fou), donc au changement de
  // sessionId un ancien override peut brievement rester affiche le temps
  // que la requete reponde - meme compromis deja accepte par
  // SnapshotSection.tsx. Le reset explicite a lieu dans switchSession/
  // startNewSession/startProjectSession (des gestionnaires d'evenements,
  // pas un effet, donc un setState synchrone y est sans probleme).
  useEffect(() => {
    if (!sessionId) return;
    fetch(`${API_BASE}/sessions/${sessionId}/model`)
      .then((r) => (r.ok ? r.json() : { model: null }))
      .then((data: { model: string | null }) => {
        setSessionModelOverride(data.model);
      })
      .catch(() => {
        setSessionModelOverride(null);
      });
  }, [sessionId]);

  // meme principe que l'effet ci-dessus pour sessionModelOverride (pas de
  // reset synchrone ici, fait dans switchSession/startNewSession/
  // startProjectSession a la place).
  useEffect(() => {
    if (!sessionId) return;
    fetch(`${API_BASE}/sessions/${sessionId}/yolo`)
      .then((r) => (r.ok ? r.json() : { enabled: false }))
      .then((data: { enabled: boolean }) => {
        setYoloEnabled(data.enabled);
      })
      .catch(() => {
        setYoloEnabled(false);
      });
  }, [sessionId]);

  function openTask(id: string) {
    setActiveTaskId(id);
    setView("task");
  }

  function stopTask(id: string) {
    fetch(`${API_BASE}/background_tasks/${id}/stop`, { method: "POST" }).catch(
      () => {
        // API hors ligne : le prochain polling reflete quand meme l'etat reel
      },
    );
  }

  function deleteTask(id: string) {
    setBackgroundTasks((prev) => prev.filter((t) => t.id !== id));
    fetch(`${API_BASE}/background_tasks/${id}`, { method: "DELETE" }).catch(
      () => {
        // API hors ligne : le prochain polling la fera reapparaitre si la
        // suppression n'a en fait pas eu lieu cote serveur
      },
    );
  }

  // `sending` n'est plus une raison de bloquer le changement de
  // conversation (voir sendMessage) : une reponse en cours pour la
  // conversation qu'on quitte continue de tourner en fond, filtree par
  // son propre session_id plutot que d'ecrire dans `messages` de celle
  // qu'on affiche desormais.
  function switchSession(id: string) {
    setView("chat");
    if (id === sessionId) return;
    setSessionId(id);
    localStorage.setItem("triton_session_id", id);
    setMessages([]);
    setActiveProjectId(sessions.find((s) => s.id === id)?.project_id ?? null);
    pendingSubagentIdsRef.current.clear();
    setBackgroundTasks([]);
    setOpenFile(null);
    setSessionModelOverride(null);
    setYoloEnabled(false);
    setAwaitingSseEvent(false);
    // restaure une confirmation d'outil laissee en attente si cette
    // conversation en a une (voir pendingConfirmationsRef dans sendMessage) -
    // null sinon, pour ne pas garder affichee celle de la conversation
    // qu'on quitte.
    setPendingConfirmation(pendingConfirmationsRef.current.get(id) ?? null);
    loadHistory(id);
  }

  const startNewSession = useCallback(() => {
    setView("chat");
    setSessionId(null);
    localStorage.removeItem("triton_session_id");
    setMessages([]);
    setActiveProjectId(null);
    pendingSubagentIdsRef.current.clear();
    setBackgroundTasks([]);
    setOpenFile(null);
    setSessionModelOverride(null);
    setYoloEnabled(false);
    setAwaitingSseEvent(false);
    setPendingConfirmation(null);
  }, [setView, setOpenFile]);

  function startProjectSession(projectId: string) {
    setView("chat");
    setSessionId(null);
    localStorage.removeItem("triton_session_id");
    setMessages([]);
    setActiveProjectId(projectId);
    pendingSubagentIdsRef.current.clear();
    setBackgroundTasks([]);
    setOpenFile(null);
    setSessionModelOverride(null);
    setYoloEnabled(false);
    setAwaitingSseEvent(false);
    setPendingConfirmation(null);
  }

  function toggleProjectCollapsed(projectId: string) {
    setCollapsedProjectIds((prev) => {
      const next = new Set(prev);
      if (next.has(projectId)) {
        next.delete(projectId);
      } else {
        next.add(projectId);
      }
      return next;
    });
  }

  function isTextAttachmentFile(file: File): boolean {
    if (file.type.startsWith("text/")) return true;
    const lower = file.name.toLowerCase();
    return TEXT_ATTACHMENT_EXTENSIONS.some((ext) => lower.endsWith(ext));
  }

  function handleFilesSelected(fileList: FileList | null) {
    if (!fileList) return;
    for (const file of Array.from(fileList)) {
      if (isTextAttachmentFile(file)) {
        if (imageMode) {
          setMessages((prev) => [
            ...prev,
            {
              kind: "error",
              text: "La génération d’images accepte uniquement des images de référence.",
              time: Date.now(),
            },
          ]);
          continue;
        }
        if (file.size > MAX_TEXT_ATTACHMENT_BYTES) {
          setMessages((prev) => [
            ...prev,
            {
              kind: "error",
              text: `« ${file.name} » dépasse la limite de ${MAX_TEXT_ATTACHMENT_BYTES / 1024} Ko pour un fichier texte, ignorée.`,
              time: Date.now(),
            },
          ]);
          continue;
        }
        void file.text().then((content) => {
          setPendingTextAttachments((prev) => [
            ...prev,
            { name: file.name, content },
          ]);
        });
        continue;
      }

      const isImage = file.type.startsWith("image/");
      const isPdf = file.type === "application/pdf";
      if (
        (isImage && !imageMode && !supportsImages) ||
        (isPdf && (imageMode || !supportsFiles)) ||
        (!isImage && !isPdf)
      ) {
        continue;
      }
      if (file.size > MAX_ATTACHMENT_BYTES) {
        setMessages((prev) => [
          ...prev,
          {
            kind: "error",
            text: `« ${file.name} » dépasse la limite de 8 Mo, ignorée.`,
            time: Date.now(),
          },
        ]);
        continue;
      }
      const reader = new FileReader();
      reader.onload = () => {
        const dataUrl = reader.result;
        if (typeof dataUrl !== "string") return;
        setPendingAttachments((prev) => [
          ...prev,
          { name: file.name, dataUrl },
        ]);
      };
      reader.readAsDataURL(file);
    }
  }

  /** Coller une image (ex. capture d'ecran) depuis le presse-papier :
   * e.clipboardData.files est deja une FileList native, exactement ce que
   * handleFilesSelected attend (meme chemin que le selecteur de fichiers
   * et le glisser-deposer) - rien de plus a faire que la lui passer. Ne
   * touche pas au comportement par defaut quand rien de collable n'est un
   * fichier (coller du texte normal dans le composer doit rester intact). */
  function handlePaste(e: React.ClipboardEvent) {
    if (e.clipboardData.files.length === 0) return;
    e.preventDefault();
    handleFilesSelected(e.clipboardData.files);
  }

  function removeAttachment(index: number) {
    setPendingAttachments((prev) => prev.filter((_, i) => i !== index));
  }

  function removeTextAttachment(index: number) {
    setPendingTextAttachments((prev) => prev.filter((_, i) => i !== index));
  }

  async function copyToClipboard(text: string, index: number) {
    await navigator.clipboard.writeText(text);
    setCopiedIndex(index);
    setTimeout(() => {
      setCopiedIndex((current) => (current === index ? null : current));
    }, 1500);
  }

  function startEditingMessage(turnIndex: number, text: string) {
    setEditingTurnIndex(turnIndex);
    setEditingText(text);
  }

  function cancelEditingMessage() {
    setEditingTurnIndex(null);
    setEditingText("");
  }

  async function submitEditedMessage() {
    if (editingTurnIndex === null) return;
    const turnIndex = editingTurnIndex;
    const text = editingText;
    setEditingTurnIndex(null);
    setEditingText("");
    await sendMessage(text, turnIndex);
  }

  /** Renvoie exactement le meme tour (meme texte, memes pieces jointes) -
   * turnIndex/msg viennent du groupe "user" precedant la reponse a
   * regenerer (voir precedingTurnIndex dans groupMessages). */
  async function regenerateResponse(
    turnIndex: number,
    msg: Extract<ChatMsg, { kind: "user" }>,
  ) {
    const attachments: PendingAttachment[] = [
      ...(msg.images ?? []).map((dataUrl) => ({ name: "", dataUrl })),
      ...(msg.files ?? []).map((f) => ({ name: f.name, dataUrl: f.dataUrl })),
    ];
    await sendMessage(msg.text, turnIndex, attachments);
  }

  const activeProject = projects.find((p) => p.id === activeProjectId) ?? null;
  // eslint-disable-next-line react-hooks/refs
  const commands = createChatCommands({
    sessionId,
    activeProjectId,
    activeProject,
    modelsCatalog,
    undoTarget,
    sending,
    pendingAttachments,
    pendingTextAttachments,
    oneShotImageModel,
    imageModel,
    getDisplayedSessionId: () => displayedSessionIdRef.current,
    setDisplayedSessionId: (id: string) => {
      displayedSessionIdRef.current = id;
    },
    getAbortControllers: () => abortControllersRef.current,
    setInput,
    setMessages,
    setSessions,
    setSessionId,
    setSessionModelOverride,
    setUndoDiff,
    setUndoTarget,
    setUndoing,
    setFileRefreshTick,
    setYoloEnabled,
    setSendingSessionIds,
    setInFlightModels,
    setOneShotImageModel,
    setPendingAttachments,
    setImageMode,
    setPreviewImage,
    loadSessions,
  });
  const {
    markSending,
    markInFlightModel,
    moveSendingKey,
    dispatchMultiAgent,
    handleCostCommand,
    handleModelCommand,
    handleUndoCommand,
    confirmUndo,
    handleRememberCommand,
    handleCompactCommand,
    handleYoloCommand,
    requestImageChange,
    generateImage,
  } = commands;

  async function sendMessage(
    rawText: string,
    editTurnIndex?: number,
    attachmentsOverride?: PendingAttachment[],
  ) {
    const text = rawText.trim();
    const isEdit = editTurnIndex !== undefined;
    if (
      (!text &&
        !isEdit &&
        pendingAttachments.length === 0 &&
        pendingTextAttachments.length === 0) ||
      sending
    ) {
      // the composer stays typable while a response is in flight (see
      // ChatComposer's isDisabled below) so an Enter press here is a real
      // possibility, not just a stray event - but ChatComposerInput's own
      // Enter-to-submit clears its value unconditionally the moment it
      // calls onSubmit (this function), before it can know sending was
      // actually true. Put the text back instead of silently losing it.
      if (!isEdit && sending) setInput(rawText);
      return;
    }

    if (!isEdit && !isWebDeployment) {
      if (text.toLowerCase().startsWith(MULTI_AGENT_PREFIX)) {
        await dispatchMultiAgent(text);
        return;
      }
      if (text === COST_COMMAND) {
        await handleCostCommand();
        return;
      }
      if (text.toLowerCase().startsWith(MODEL_COMMAND_PREFIX)) {
        await handleModelCommand(text);
        return;
      }
      if (text === UNDO_COMMAND) {
        await handleUndoCommand();
        return;
      }
      if (text.toLowerCase().startsWith(REMEMBER_PREFIX)) {
        await handleRememberCommand(text);
        return;
      }
      if (text === COMPACT_COMMAND) {
        await handleCompactCommand();
        return;
      }
      if (text === YOLO_COMMAND) {
        await handleYoloCommand();
        return;
      }
    }

    const requestModel = isEdit ? null : oneShotChatModel;
    const inFlightModel = requestModel ?? effectiveModel;
    if (!isEdit) setOneShotChatModel(null);
    const attachments = isEdit
      ? (attachmentsOverride ?? [])
      : pendingAttachments;
    const textAttachments = isEdit ? [] : pendingTextAttachments;

    const sentImages = attachments
      .filter((a) => !isPdfDataUrl(a.dataUrl))
      .map((a) => a.dataUrl);
    const sentFiles = attachments.filter((a) => isPdfDataUrl(a.dataUrl));

    // les fichiers texte n'existent pas comme piece jointe pour le serveur
    // (voir PendingTextAttachment) : leur contenu est colle tel quel dans le
    // texte du message, avant meme d'etre affiche - donc identique a la
    // relecture depuis l'historique, pas de reconstruction speciale requise.
    const outgoingText = [
      text,
      ...textAttachments.map(
        (a) => `--- ${a.name} ---\n\`\`\`\n${a.content}\n\`\`\``,
      ),
    ]
      .filter(Boolean)
      .join("\n\n");

    if (!isEdit) {
      setInput("");
      setPendingAttachments([]);
      setPendingTextAttachments([]);
    }

    const startSessionId = sessionId;
    if (displayedSessionIdRef.current === startSessionId) {
      setMessages((prev) => {
        const base = isEdit ? truncateBeforeTurn(prev, editTurnIndex) : prev;
        return [
          ...base,
          {
            kind: "user",
            text: outgoingText,
            time: Date.now(),
            images: sentImages.length ? sentImages : undefined,
            files: sentFiles.length ? sentFiles : undefined,
          },
        ];
      });
    }

    await runChatConversationStream({
      request: {
        session_id: startSessionId,
        message: outgoingText,
        project_id: activeProjectId,
        attachments: attachments.map((attachment) => ({
          name: attachment.name,
          data_url: attachment.dataUrl,
        })),
        edit_turn_index: editTurnIndex ?? null,
        model: requestModel,
      },
      inFlightModel,
      initialSessionId: startSessionId,
      isDisplayed: (targetSessionId) =>
        displayedSessionIdRef.current === targetSessionId,
      updateMessages: setMessages,
      updateSessions: setSessions,
      setSessionCreated: (id) => {
        setSessionId(id);
        localStorage.setItem("triton_session_id", id);
        displayedSessionIdRef.current = id;
      },
      markSending,
      markInFlightModel,
      moveSendingKey,
      setFileRefreshTick,
      addPendingSubagent: (id) => pendingSubagentIdsRef.current.add(id),
      setPendingConfirmation,
      pendingConfirmations: pendingConfirmationsRef.current,
      abortControllers: abortControllersRef.current,
      onStreamEvent: () => {
        if (sseIdleTimerRef.current !== null) clearTimeout(sseIdleTimerRef.current);
        setAwaitingSseEvent(false);
        sseIdleTimerRef.current = setTimeout(() => {
          setAwaitingSseEvent(true);
        }, SSE_IDLE_MS);
      },
      onStreamFinished: () => {
        if (sseIdleTimerRef.current !== null) {
          clearTimeout(sseIdleTimerRef.current);
          sseIdleTimerRef.current = null;
        }
        setAwaitingSseEvent(false);
      },
      refreshSessions: () => {
        void loadSessions();
      },
      notifyCompletion: (text) => {
        notifyIfBackground("Triton a terminé", text);
      },
    });
  }

  useEffect(() => {
    sendMessageRef.current = (text: string) => {
      void sendMessage(text);
    };
  });

  // memoisee (useCallback) : referencee par cancelMessage ci-dessous, elle
  // meme dans les dependances de l'effet echap.
  const respondToConfirmation = useCallback(
    async (approved: boolean, remember = false) => {
      if (!pendingConfirmation) return;
      const { id, sessionId: confirmationSessionId } = pendingConfirmation;
      setPendingConfirmation(null);
      pendingConfirmationsRef.current.delete(confirmationSessionId);

      await fetch(`${API_BASE}/chat/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirmation_id: id, approved, remember }),
      });
    },
    [pendingConfirmation],
  );

  /** Interrompt la conversation en cours (celle affichee) : ferme le flux
   * SSE cote client, signale au serveur d'arreter la boucle agentique
   * avant sa prochaine iteration, et refuse une confirmation d'outil
   * eventuellement en attente pour ne pas laisser le serveur bloque
   * dessus jusqu'au timeout. Memoisee (useCallback) car referencee dans
   * les dependances de l'effet echap ci-dessous. */
  const cancelMessage = useCallback(() => {
    if (!sending) return;
    if (pendingConfirmation) {
      void respondToConfirmation(false);
    }
    if (sessionId) {
      void fetch(`${API_BASE}/chat/cancel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId }),
      });
    }
    abortControllersRef.current.get(sessionId ?? "")?.abort();
  }, [sending, pendingConfirmation, sessionId, respondToConfirmation]);

  // touche echap pour interrompre la reponse en cours, tant qu'une reponse
  // est effectivement en cours (sending) ; reattache a chaque changement de
  // sessionId pour que cancelMessage() cible toujours la bonne conversation
  // (utile pour une toute nouvelle conversation : sessionId passe de null a
  // son id reel des le premier evenement SSE, pendant que sending est deja true).
  useEffect(() => {
    if (!sending) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") cancelMessage();
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [sending, cancelMessage]);

  // cmd/ctrl+entree pour "autoriser une fois", cmd/ctrl+maj+entree pour
  // "toujours autoriser" - memes raccourcis que la demande d'autorisation
  // de Claude Desktop (echap = refuser vient deja de l'effet ci-dessus,
  // cancelMessage refusant toute confirmation en attente).
  useEffect(() => {
    if (!pendingConfirmation) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (!(e.metaKey || e.ctrlKey) || e.key !== "Enter") return;
      e.preventDefault();
      void respondToConfirmation(true, e.shiftKey);
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [pendingConfirmation, respondToConfirmation]);

  // raccourcis globaux, actifs partout dans l'app (pas seulement pendant une
  // reponse en cours, contrairement a echap ci-dessus) : cmd/ctrl+K pour la
  // recherche, cmd/ctrl+N pour une nouvelle conversation.
  useEffect(() => {
    function handleGlobalShortcuts(e: KeyboardEvent) {
      if (!(e.metaKey || e.ctrlKey)) return;
      if (e.key.toLowerCase() === "k") {
        e.preventDefault();
        setView("search");
      } else if (e.key.toLowerCase() === "n") {
        e.preventDefault();
        startNewSession();
      }
    }
    document.addEventListener("keydown", handleGlobalShortcuts);
    return () => {
      document.removeEventListener("keydown", handleGlobalShortcuts);
    };
  }, [startNewSession]);

  // liste des conversations hors projet, telle qu'affichee dans la sidebar
  // (la recherche par titre/contenu est sa propre page - voir SearchPage.tsx)
  // - epinglees d'abord, tri stable donc l'ordre naturel (le plus recent en
  // tete, deja garanti par loadSessions) est preserve au sein de chaque groupe.
  const topLevelSessions = sessions.filter((s) => s.project_id === null);

  // affiche un message assistant "vide" avec un loader tant qu'aucun texte
  // n'est en train d'arriver pour ce tour. Volontairement PAS exclu quand
  // le dernier message est "tool" (contrairement a une version precedente
  // qui le cachait des le premier appel d'outil) : un tour a plusieurs
  // outils d'affilee a un vrai temps mort entre la fin d'un appel et le
  // debut du suivant (le modele "reflechit" a nouveau), pendant lequel
  // plus aucun indicateur ne s'affichait - voir la conversation "Triton
  // Folder" pour un exemple ou 20 appels d'outils s'enchainent sans loader
  // entre chacun. Le meme trou existe quand le dernier message est du
  // texte assistant suivi d'un appel d'outil (ex. "Je vais ecrire X."
  // avant un write_file qui prend plusieurs secondes) : le texte fini de
  // s'afficher, plus aucun evenement SSE n'arrive tant que l'outil tourne,
  // mais lastMessage reste "assistant" - awaitingSseEvent (minuteur de
  // silence, voir sendMessage's noteSseEvent) couvre ce cas-la aussi, sans
  // faire clignoter le loader pendant un flux de texte actif (les tokens
  // arrivent bien plus vite que SSE_IDLE_MS).
  const lastMessage = messages[messages.length - 1];
  const showTypingPlaceholder =
    sending &&
    !pendingConfirmation &&
    (lastMessage?.kind !== "assistant" || awaitingSseEvent);
  // le modele de CETTE conversation, une fois la surcharge /model prise en
  // compte - c'est celui-ci qui doit determiner l'affichage (badge, avatar,
  // capacites de piece jointe), pas le defaut global apiModel seul.
  const effectiveModel = sessionModelOverride ?? apiModel;
  const displayedInFlightModel = inFlightModels[sessionId ?? ""] ?? effectiveModel;
  const currentModelInfo = modelsCatalog.find((m) => m.id === effectiveModel);
  const supportsImages = currentModelInfo?.supports_images ?? false;
  const supportsFiles = currentModelInfo?.supports_files ?? false;
  // les fichiers texte (accept toujours inclus) sont colles dans le texte
  // du message plutot qu'envoyes comme piece jointe binaire (voir
  // PendingTextAttachment) - n'importe quel modele les comprend, donc pas
  // besoin de verifier supportsImages/supportsFiles pour eux.
  const attachAccept = [
    supportsImages ? "image/*" : null,
    supportsFiles ? "application/pdf" : null,
    TEXT_ATTACHMENT_EXTENSIONS.join(","),
  ]
    .filter((x): x is string => x !== null)
    .join(",");
  const attachLabel =
    supportsImages && supportsFiles
      ? "Joindre une image, un PDF ou un fichier texte"
      : supportsImages
        ? "Joindre une image ou un fichier texte"
        : supportsFiles
          ? "Joindre un PDF ou un fichier texte"
          : "Joindre un fichier texte";

  // eslint-disable-next-line react-hooks/refs
  const sidebarHeader = SidebarHeader({
    usesMacTitlebarOverlay,
    sidebarCollapsed,
    onToggleSidebar: toggleSidebar,
    onSearch: () => {
      setView("search");
    },
    onNewConversation: startNewSession,
  });

  const sideNavElement = (
    <SideNav
      header={sidebarHeader.header}
      topContent={sidebarHeader.topContent}
    >
      {remoteProjectsEnabled && <ProjectSidebarSection
        projects={projects}
        sessions={sessions}
        activeProjectId={activeProjectId}
        activeSessionId={sessionId}
        sendingSessionIds={sendingSessionIds}
        collapsedProjectIds={collapsedProjectIds}
        editingProjectId={editingProjectId}
        editingProjectValue={editingProjectValue}
        editingSessionId={editingSessionId}
        editingValue={editingValue}
        onNewProject={() => {
          setShowProjectForm(true);
        }}
        onToggleCollapse={toggleProjectCollapsed}
        onNewProjectConversation={startProjectSession}
        onStartRenameProject={startRenameProject}
        onDeleteProject={setDeletingProject}
        onEditingProjectValueChange={setEditingProjectValue}
        onCommitRenameProject={(id) => {
          void commitRenameProject(id);
        }}
        onCancelRenameProject={() => {
          setEditingProjectId(null);
        }}
        onSwitchSession={switchSession}
        onStartRenameSession={startRename}
        onTogglePinSession={(session) => {
          void togglePin(session);
        }}
        onDeleteSession={setDeletingSession}
        onEditingValueChange={setEditingValue}
        onCommitRenameSession={(id) => {
          void commitRename(id);
        }}
        onCancelRenameSession={() => {
          setEditingSessionId(null);
        }}
      />}

      {remoteProjectsEnabled && <SubagentsPanel />}

      <ConversationSidebarSection
        sessions={topLevelSessions}
        activeSessionId={sessionId}
        sendingSessionIds={sendingSessionIds}
        editingSessionId={editingSessionId}
        editingValue={editingValue}
        onSwitchSession={switchSession}
        onStartRename={startRename}
        onTogglePin={(session) => {
          void togglePin(session);
        }}
        onDelete={setDeletingSession}
        onEditingValueChange={setEditingValue}
        onCommitRename={(id) => {
          void commitRename(id);
        }}
        onCancelRename={() => {
          setEditingSessionId(null);
        }}
      />
    </SideNav>
  );

  return (
    <Theme theme={neutralTheme} mode={themeMode}>
      <div className="flex h-full min-h-0 flex-col bg-surface">
        {usesMacTitlebarOverlay && (
          <DesktopTitlebar
            sidebarCollapsed={sidebarCollapsed}
            onToggleSidebar={toggleSidebar}
          />
        )}
        <div className="min-h-0 flex-1">
          {sidebarCollapsed && (
            <div
              className={`fixed bottom-0 left-0 z-40 w-2 ${
                usesMacTitlebarOverlay ? "top-[44px]" : "top-0"
              }`}
              onMouseEnter={() => {
                setSidebarPeeking(true);
              }}
            />
          )}
          {sidebarCollapsed && sidebarPeeking && (
            <div
              className={`fixed bottom-0 left-0 z-50 shadow-2xl ${
                usesMacTitlebarOverlay ? "top-[44px]" : "top-0"
              }`}
              onMouseLeave={() => {
                setSidebarPeeking(false);
              }}
            >
              {sideNavElement}
            </div>
          )}
          <AppShell
            variant="elevated"
            height="fill"
            sideNav={sidebarCollapsed ? undefined : sideNavElement}
          >
            {view === "task" && activeTaskId && (
              <TaskView
                key={activeTaskId}
                taskId={activeTaskId}
                onBack={() => {
                  setView("chat");
                }}
              />
            )}
            {view === "search" && (
              <SearchPage
                onBack={() => {
                  setView("chat");
                }}
                onSelectSession={switchSession}
              />
            )}
            {view === "snapshot_history" && sessionId && (
              <SnapshotHistoryView
                key={sessionId}
                sessionId={sessionId}
                onBack={() => {
                  setView("chat");
                }}
                onRestored={() => {
                  setFileRefreshTick((t) => t + 1);
                  setView("chat");
                }}
              />
            )}
            {view === "chat" && (
              <div
                className="relative flex h-full min-h-0"
                onPaste={handlePaste}
                onDragEnter={(e) => {
                  e.preventDefault();
                  setDragDepth((d) => d + 1);
                }}
                onDragLeave={(e) => {
                  e.preventDefault();
                  setDragDepth((d) => Math.max(0, d - 1));
                }}
                onDragOver={(e) => {
                  e.preventDefault();
                }}
                onDrop={(e) => {
                  e.preventDefault();
                  setDragDepth(0);
                  handleFilesSelected(e.dataTransfer.files);
                }}
              >
                {dragDepth > 0 && (
                  <div className="pointer-events-none absolute inset-2 z-50 flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-accent bg-surface/90">
                    <FileIcon className="h-8 w-8 text-accent" />
                    <Text weight="medium" className="text-accent">
                      Déposer pour joindre
                    </Text>
                  </div>
                )}
                <ChatLayout
                  ref={chatScrollRef}
                  density="spacious"
                  style={{ marginBottom: 52 }}
                  className="min-h-0 min-w-0 flex-1"
                  emptyState={
                    <EmptyState
                      title="Nouvelle conversation"
                      description="Écris un message pour démarrer la conversation."
                    />
                  }
                  scrollButton={
                    <ChatLayoutScrollButton
                      isVisible={showScrollButton}
                      label={hasNewMessage ? "Nouveaux messages" : undefined}
                      onClick={() => {
                        chatScrollRef.current?.scrollTo({
                          top: chatScrollRef.current.scrollHeight,
                          behavior: "smooth",
                        });
                        setHasNewMessage(false);
                      }}
                    />
                  }
                  composer={
                    <ChatComposer
                      value={input}
                      onChange={setInput}
                      onSubmit={(value) => {
                        if (imageMode) {
                          void generateImage(value);
                        } else {
                          void sendMessage(value);
                        }
                      }}
                      onStop={cancelMessage}
                      isStopShown={sending}
                      placeholder={imageMode ? "Décrire l’image à générer…" : "Écrire un message..."}
                      // sending is deliberately NOT here: isDisabled greys the
                      // whole composer out (opacity 0.6) and makes its input
                      // non-editable (contentEditable=false) - there's no
                      // reason typing ahead while a response streams should be
                      // blocked. Actually sending a new message meanwhile is
                      // still guarded inside sendMessage itself. A
                      // confirmation prompt is different: genuinely blocking,
                      // has to be resolved first.
                      isDisabled={!!pendingConfirmation}
                      elevation="none"
                      input={<ChatComposerInput triggers={composerTriggers} />}
                      style={
                        { "--_chat-composer-padding": "24px" } as CSSProperties
                      }
                      drawer={
                        pendingAttachments.length > 0 ||
                        pendingTextAttachments.length > 0 ? (
                          <ChatComposerDrawer
                            count={
                              pendingAttachments.length +
                              pendingTextAttachments.length
                            }
                            label="pièce(s) jointe(s)"
                          >
                            <div className="flex flex-wrap gap-2">
                              {pendingAttachments.map((a, i) =>
                                isPdfDataUrl(a.dataUrl) ? (
                                  <div
                                    key={`${a.name}-${i}`}
                                    className="relative flex h-16 w-32 items-center gap-1.5 rounded-md border border-border px-2"
                                  >
                                    <FileIcon className="h-4 w-4 shrink-0 text-secondary" />
                                    <Text
                                      size="2xs"
                                      className="min-w-0 truncate"
                                    >
                                      {a.name}
                                    </Text>
                                    <IconButton
                                      label="Retirer"
                                      icon={<XIcon className="h-3 w-3" />}
                                      variant="primary"
                                      size="sm"
                                      className="absolute -right-1.5 -top-1.5 h-5 w-5 min-w-0 rounded-full p-0"
                                      onClick={() => {
                                        removeAttachment(i);
                                      }}
                                    />
                                  </div>
                                ) : (
                                  <div
                                    key={`${a.name}-${i}`}
                                    className="relative"
                                  >
                                    <img
                                      src={a.dataUrl}
                                      alt={a.name}
                                      className="h-16 w-16 rounded-md border border-border object-cover"
                                    />
                                    <IconButton
                                      label="Retirer"
                                      icon={<XIcon className="h-3 w-3" />}
                                      variant="primary"
                                      size="sm"
                                      className="absolute -right-1.5 -top-1.5 h-5 w-5 min-w-0 rounded-full p-0"
                                      onClick={() => {
                                        removeAttachment(i);
                                      }}
                                    />
                                  </div>
                                ),
                              )}
                              {pendingTextAttachments.map((a, i) => (
                                <div
                                  key={`${a.name}-${i}`}
                                  className="relative flex h-16 w-32 items-center gap-1.5 rounded-md border border-border px-2"
                                >
                                  <FileIcon className="h-4 w-4 shrink-0 text-secondary" />
                                  <Text size="2xs" className="min-w-0 truncate">
                                    {a.name}
                                  </Text>
                                  <IconButton
                                    label="Retirer"
                                    icon={<XIcon className="h-3 w-3" />}
                                    variant="primary"
                                    size="sm"
                                    className="absolute -right-1.5 -top-1.5 h-5 w-5 min-w-0 rounded-full p-0"
                                    onClick={() => {
                                      removeTextAttachment(i);
                                    }}
                                  />
                                </div>
                              ))}
                            </div>
                          </ChatComposerDrawer>
                        ) : undefined
                      }
                      footerActions={
                        <>
                          <input
                            ref={fileInputRef}
                            type="file"
                            accept={imageMode ? "image/*" : attachAccept}
                            multiple
                            className="hidden"
                            onChange={(e) => {
                              handleFilesSelected(e.target.files);
                              e.target.value = "";
                            }}
                          />
                          <IconButton
                            label={imageMode ? "Ajouter une image de référence" : attachLabel}
                            icon={<PlusIcon />}
                            variant="ghost"
                            size="sm"
                            isDisabled={!imageMode && !supportsImages && !supportsFiles}
                            onClick={() => {
                              fileInputRef.current?.click();
                            }}
                          />
                          <IconButton
                            label={imageMode ? "Revenir au chat" : "Générer une image"}
                            icon={<ImageIcon />}
                            variant={imageMode ? "primary" : "ghost"}
                            size="sm"
                            isDisabled={
                              pendingTextAttachments.length > 0 ||
                              pendingAttachments.some((attachment) => isPdfDataUrl(attachment.dataUrl))
                            }
                            onClick={() => {
                              setImageMode((active) => !active);
                            }}
                          />
                        </>
                      }
                      sendActions={
                        <>
                          {yoloEnabled && (
                            <Badge variant="warning" label="YOLO actif" />
                          )}
                          <select
                            aria-label={imageMode ? "Modèle image pour cette génération" : "Modèle chat pour ce message"}
                            value={imageMode ? (oneShotImageModel ?? "") : (oneShotChatModel ?? "")}
                            className="max-w-48 rounded-md border border-border bg-surface px-2 py-1 text-xs text-primary outline-none focus:border-accent"
                            onChange={(event) => {
                              if (imageMode) setOneShotImageModel(event.target.value || null);
                              else setOneShotChatModel(event.target.value || null);
                            }}
                          >
                            {imageMode ? (
                              <>
                                <option value="">Par défaut : {imageModel ?? "—"}</option>
                                {imageModelsCatalog.map((model) => (
                                  <option key={model.id} value={model.id}>{model.name}</option>
                                ))}
                              </>
                            ) : (
                              <>
                                <option value="">Conversation : {effectiveModel ?? "—"}</option>
                                {modelsCatalog.map((model) => (
                                  <option key={model.id} value={model.id}>{model.name}</option>
                                ))}
                              </>
                            )}
                          </select>
                          <Badge
                            variant={imageMode ? "warning" : "neutral"}
                            label={
                              imageMode
                                ? oneShotImageModel
                                  ? "Modèle temporaire"
                                  : "Image"
                                : oneShotChatModel
                                  ? "Modèle temporaire"
                                  : effectiveModel ?? "Modèle"
                            }
                          />
                        </>
                      }
                    />
                  }
                >
                  <ChatMessageList isStreaming={sending}>
                    {(() => {
                      const groups = groupMessages(messages);
                      return groups.map((group, gi) => {
                        if (group.type === "user") {
                          const isEditingThis =
                            editingTurnIndex === group.turnIndex;
                          return (
                            <ChatMessage
                              key={gi}
                              sender="user"
                              className="animate-fade-in"
                            >
                              <ChatMessageBubble
                                metadata={
                                  <ChatMessageMetadata
                                    timestamp={
                                      <Timestamp
                                        value={group.msg.time / 1000}
                                        format="time"
                                      />
                                    }
                                    status="sent"
                                    footer={
                                      !isEditingThis && !sending ? (
                                        <button
                                          onClick={() => {
                                            startEditingMessage(
                                              group.turnIndex,
                                              group.msg.text,
                                            );
                                          }}
                                          className="inline-flex items-center gap-1 text-secondary hover:text-primary"
                                          title="Modifier"
                                          aria-label="Modifier"
                                        >
                                          <PencilIcon className="h-3.5 w-3.5" />
                                        </button>
                                      ) : undefined
                                    }
                                  />
                                }
                              >
                                {group.msg.images &&
                                  group.msg.images.length > 0 && (
                                    <div className="mb-2 flex flex-wrap gap-2">
                                      {group.msg.images.map((src, i) => (
                                        <img
                                          key={i}
                                          src={src}
                                          alt=""
                                          className="max-h-48 rounded-md border border-border object-cover"
                                        />
                                      ))}
                                    </div>
                                  )}
                                {group.msg.files &&
                                  group.msg.files.length > 0 && (
                                    <div className="mb-2 flex flex-wrap gap-2">
                                      {group.msg.files.map((f, i) => (
                                        <div
                                          key={i}
                                          className="flex items-center gap-1.5 rounded-md border border-border px-2 py-1"
                                        >
                                          <FileIcon className="h-4 w-4 shrink-0 text-secondary" />
                                          <Text size="2xs">{f.name}</Text>
                                        </div>
                                      ))}
                                    </div>
                                  )}
                                {isEditingThis ? (
                                  <div className="flex flex-col gap-2">
                                    <textarea
                                      value={editingText}
                                      onChange={(e) => {
                                        setEditingText(e.target.value);
                                      }}
                                      onKeyDown={(e) => {
                                        if (e.key === "Enter" && !e.shiftKey) {
                                          e.preventDefault();
                                          void submitEditedMessage();
                                        } else if (e.key === "Escape") {
                                          cancelEditingMessage();
                                        }
                                      }}
                                      // ouvert par un clic explicite de l'utilisateur (pas au chargement de la page)
                                      autoFocus
                                      rows={Math.min(
                                        8,
                                        editingText.split("\n").length + 1,
                                      )}
                                      className="w-full resize-none rounded-md border border-border bg-transparent p-2 text-sm"
                                    />
                                    <div className="flex justify-end gap-2">
                                      <Button
                                        label="Annuler"
                                        variant="ghost"
                                        size="sm"
                                        onClick={cancelEditingMessage}
                                      />
                                      <Button
                                        label="Renvoyer"
                                        variant="primary"
                                        size="sm"
                                        isDisabled={!editingText.trim()}
                                        onClick={() => {
                                          void submitEditedMessage();
                                        }}
                                      />
                                    </div>
                                  </div>
                                ) : (
                                  group.msg.text
                                )}
                              </ChatMessageBubble>
                            </ChatMessage>
                          );
                        }

                        if (group.type === "system") {
                          return (
                            <ChatSystemMessage
                              key={gi}
                              className="animate-fade-in"
                            >
                              {group.msg.kind === "error" ? (
                                <span className="text-error">
                                  {group.msg.text}
                                </span>
                              ) : (
                                group.msg.text
                              )}
                            </ChatSystemMessage>
                          );
                        }

                        const blocks = toBlocks(group.items);
                        const generatedImages = group.items.flatMap((item) =>
                          item.kind === "assistant" ? item.images ?? [] : [],
                        );
                        const lastItem = group.items[group.items.length - 1];
                        // groupMessages() ne cree jamais un groupe "assistant" avec un
                        // tableau items vide (toujours au moins un push initial) : ceci
                        // n'est qu'un garde-fou pour TypeScript (noUncheckedIndexedAccess).
                        if (!lastItem)
                          throw new Error("groupe assistant sans element");
                        const lastIsText = lastItem.kind === "assistant";
                        // le modele qui a effectivement repondu dans ce groupe (pas
                        // forcement celui actuellement selectionne dans les parametres,
                        // qui a pu changer depuis) ; undefined pour un historique
                        // enregistre avant l'ajout de ce champ, l'avatar retombe alors
                        // sur les initiales.
                        // A response may contain several assistant fragments
                        // around tool calls. Older saved conversations did
                        // not record `model` on those intermediate fragments,
                        // while the final fragment does have it. Pick any
                        // known model in the group (from the end, which is
                        // normally the final answer) instead of letting one
                        // missing value turn the avatar back into Triton.
                        const groupModel = assistantGroupModel(group.items);
                        const messageAvatar = modelAvatar(groupModel ?? null);

                        return (
                          <ChatMessage
                            key={gi}
                            sender="assistant"
                            className="animate-fade-in"
                            avatar={
                              <Avatar
                                name={messageAvatar.name}
                                src={messageAvatar.logo}
                                size={72}
                                // ceinture-bretelles en plus de `size` : la derniere
                                // fois, l'image (1024x1024 a la source) a fini par
                                // s'afficher a sa taille native au lieu d'etre
                                // contrainte a la taille demandee, debordant tout
                                // le fil de discussion horizontalement (plus moyen
                                // de scroller). w-/h- fixes + overflow-hidden sur
                                // ce meme element forcent un plafond quoi qu'il
                                // arrive cote taille interne du composant Avatar.
                                className="h-[72px] w-[72px] shrink-0 overflow-hidden"
                              />
                            }
                            name="Triton"
                          >
                            {generatedImages.length > 0 && (
                              <div className="mb-3 flex flex-wrap gap-3">
                                {generatedImages.map((src, imageIndex) => (
                                  <button
                                    type="button"
                                    key={`${src.slice(0, 48)}-${imageIndex}`}
                                    className="block overflow-hidden rounded-xl border border-border bg-surface"
                                    title="Agrandir l’image"
                                    onClick={() => {
                                      setPreviewImage(src);
                                    }}
                                  >
                                    <img
                                      src={src}
                                      alt="Image générée"
                                      className="max-h-[32rem] max-w-full object-contain"
                                    />
                                  </button>
                                ))}
                              </div>
                            )}
                            {blocks.map((block, bi) => {
                              // un show_map/show_link_preview isole (pas
                              // regroupe avec d'autres appels d'outils,
                              // voir toBlocks) se rend en carte plutot
                              // qu'en ligne de tool-call repliable - tout
                              // le reste (y compris ces deux outils
                              // regroupes avec d'autres) garde le rendu
                              // generique ci-dessous.
                              const soleToolCall =
                                block.kind === "tools" &&
                                block.items.length === 1
                                  ? block.items[0]
                                  : undefined;
                              const richCard = soleToolCall
                                ? richCardFromToolCall(
                                    soleToolCall.tool,
                                    soleToolCall.args,
                                  )
                                : null;
                              if (richCard) {
                                return <RichCard key={bi} card={richCard} />;
                              }
                              return block.kind === "tools" ? (
                                <ChatToolCalls
                                  key={bi}
                                  className="animate-fade-in"
                                  defaultIsExpanded
                                  calls={block.items.map((t) => {
                                    const isSubtask =
                                      t.subtaskToolCalls !== undefined;
                                    const status =
                                      t.status ?? toolCallStatus(t.result);
                                    const callCount =
                                      t.subtaskToolCalls?.length ?? 0;
                                    return {
                                      name: t.tool,
                                      status,
                                      node:
                                        isSubtask &&
                                        typeof t.args.model === "string"
                                          ? t.args.model
                                          : t.tool === "web_search"
                                            ? webSearchSource(t.result)
                                            : undefined,
                                      target: isSubtask
                                        ? t.subtaskDescription
                                        : t.tool === "edit_file"
                                          ? editFileTarget(t.args)
                                          : formatArgs(t.args),
                                      stats:
                                        isSubtask &&
                                        status === "running" &&
                                        callCount > 0
                                          ? `${callCount} outil${callCount > 1 ? "s" : ""}`
                                          : undefined,
                                      ...(isSubtask ? {} : toolDiffStats(t)),
                                      resultDetail: isSubtask
                                        ? multiAgentSubtaskDetail(t)
                                        : toolResultDetail(t),
                                    };
                                  })}
                                />
                              ) : block.msg.text ? (
                                <ChatMessageBubble
                                  key={bi}
                                  variant="ghost"
                                  width="100%"
                                  className="animate-fade-in"
                                >
                                  <Markdown>{block.msg.text}</Markdown>
                                </ChatMessageBubble>
                              ) : null;
                            })}
                            <ChatMessageMetadata
                              timestamp={
                                <Timestamp
                                  value={lastItem.time / 1000}
                                  format="time"
                                />
                              }
                              footer={
                                lastIsText && lastItem.text ? (
                                  <div className="inline-flex items-center gap-3">
                                    <button
                                      onClick={() => {
                                        void copyToClipboard(lastItem.text, gi);
                                      }}
                                      className="inline-flex items-center gap-1 text-secondary hover:text-primary"
                                      title="Copier"
                                      aria-label="Copier"
                                    >
                                      {copiedIndex === gi ? (
                                        <CheckIcon className="h-3.5 w-3.5" />
                                      ) : (
                                        <CopyIcon className="h-3.5 w-3.5" />
                                      )}
                                    </button>
                                    {/* regenerer n'a de sens que sur la toute
                                  derniere reponse - regenerer une reponse
                                  plus ancienne ecraserait tout ce qui suit,
                                  pas juste elle */}
                                    {gi === groups.length - 1 && !sending && (
                                      <button
                                        onClick={() => {
                                          const userMsg = userMessageAtTurn(
                                            messages,
                                            group.precedingTurnIndex,
                                          );
                                          if (userMsg) {
                                            void regenerateResponse(
                                              group.precedingTurnIndex,
                                              userMsg,
                                            );
                                          }
                                        }}
                                        className="inline-flex items-center gap-1 text-secondary hover:text-primary"
                                        title="Regenerer"
                                        aria-label="Regenerer"
                                      >
                                        <RefreshIcon className="h-3.5 w-3.5" />
                                      </button>
                                    )}
                                  </div>
                                ) : undefined
                              }
                            />
                          </ChatMessage>
                        );
                      });
                    })()}

                    {showTypingPlaceholder && (
                      <ChatMessage
                        sender="assistant"
                        className="animate-fade-in"
                        avatar={
                          <Avatar
                            name={modelAvatar(displayedInFlightModel).name}
                            src={modelAvatar(displayedInFlightModel).logo}
                            size={72}
                            className="h-[72px] w-[72px] shrink-0 overflow-hidden"
                          />
                        }
                        name="Triton"
                      >
                        <ChatMessageBubble variant="ghost" width="100%">
                          <Spinner
                            size="sm"
                            shade="subtle"
                            aria-label="Triton réfléchit"
                          />
                        </ChatMessageBubble>
                      </ChatMessage>
                    )}

                    {pendingConfirmation &&
                      (() => {
                        const { label, server } = parseToolDisplay(
                          pendingConfirmation.tool,
                        );
                        const hasDetails =
                          (pendingConfirmation.tool === "edit_file" &&
                            parseEditFileEdits(pendingConfirmation.args)
                              .length > 0) ||
                          (pendingConfirmation.tool === "write_file" &&
                            !!activeProject &&
                            typeof pendingConfirmation.args.path === "string" &&
                            typeof pendingConfirmation.args.content ===
                              "string") ||
                          Object.keys(pendingConfirmation.args).length > 0;

                        return (
                          <div className="mx-auto flex w-full max-w-sm flex-col items-center gap-4 rounded-2xl border border-border bg-surface px-6 py-6">
                            <Avatar name={server ?? label} size="lg" />

                            <button
                              type="button"
                              disabled={!hasDetails}
                              className="flex items-center gap-1 text-center text-sm disabled:cursor-default"
                              onClick={() => {
                                setConfirmationDetailsExpanded((v) => !v);
                              }}
                            >
                              <span>
                                Triton souhaite utiliser{" "}
                                <strong>{label}</strong>
                                {server && (
                                  <>
                                    {" "}
                                    de <strong>{server}</strong>
                                  </>
                                )}
                                .
                              </span>
                              {hasDetails && (
                                <ChevronRightIcon
                                  className={`h-4 w-4 shrink-0 text-secondary transition-transform ${
                                    confirmationDetailsExpanded
                                      ? "rotate-90"
                                      : ""
                                  }`}
                                />
                              )}
                            </button>

                            {confirmationDetailsExpanded && (
                              <div className="w-full">
                                <Text
                                  size="sm"
                                  color="secondary"
                                  className="mb-2 block break-words text-center"
                                >
                                  {pendingConfirmation.tool === "edit_file"
                                    ? editFileTarget(pendingConfirmation.args)
                                    : formatArgs(pendingConfirmation.args)}
                                </Text>
                                {pendingConfirmation.tool === "edit_file" &&
                                  parseEditFileEdits(pendingConfirmation.args)
                                    .length > 0 && (
                                    <EditFileEdits
                                      edits={parseEditFileEdits(
                                        pendingConfirmation.args,
                                      )}
                                    />
                                  )}
                                {pendingConfirmation.tool === "write_file" &&
                                  activeProject &&
                                  typeof pendingConfirmation.args.path ===
                                    "string" &&
                                  typeof pendingConfirmation.args.content ===
                                    "string" && (
                                    <WriteFileDiff
                                      projectId={activeProject.id}
                                      path={pendingConfirmation.args.path}
                                      newContent={
                                        pendingConfirmation.args.content
                                      }
                                    />
                                  )}
                              </div>
                            )}

                            <div className="flex w-full flex-col gap-2">
                              <Button
                                label="Refuser"
                                variant="ghost"
                                size="md"
                                className="w-full"
                                endContent={
                                  <kbd className="rounded border border-border px-1.5 py-0.5 text-xs text-secondary">
                                    Échap
                                  </kbd>
                                }
                                onClick={() => {
                                  void respondToConfirmation(false);
                                }}
                              >
                                Refuser
                              </Button>
                              <Button
                                label="Toujours autoriser pour cette conversation"
                                variant="secondary"
                                size="md"
                                className="w-full"
                                endContent={
                                  <kbd className="rounded border border-border px-1.5 py-0.5 text-xs text-secondary">
                                    ⇧⌘⏎
                                  </kbd>
                                }
                                onClick={() => {
                                  void respondToConfirmation(true, true);
                                }}
                              >
                                Toujours autoriser
                              </Button>
                              <Button
                                label="Autoriser une fois"
                                variant="primary"
                                size="md"
                                className="w-full"
                                endContent={
                                  <kbd className="rounded border border-white/30 px-1.5 py-0.5 text-xs">
                                    ⌘⏎
                                  </kbd>
                                }
                                onClick={() => {
                                  void respondToConfirmation(true);
                                }}
                              >
                                Autoriser une fois
                              </Button>
                            </div>
                          </div>
                        );
                      })()}
                  </ChatMessageList>
                </ChatLayout>
                {remoteProjectsEnabled && activeProject && openFile ? (
                  <FileViewerPanel
                    key={`${openFile.projectId}:${openFile.path}`}
                    file={openFile}
                    onClose={() => {
                      setOpenFile(null);
                    }}
                  />
                ) : remoteProjectsEnabled && activeProject ? (
                  <ProjectFilePanel
                    projectId={activeProject.id}
                    projectName={activeProject.name}
                    folderPath={activeProject.folder_path}
                    refreshSignal={fileRefreshTick}
                    sessionId={sessionId}
                    onOpenHistory={() => {
                      setView("snapshot_history");
                    }}
                    tasks={backgroundTasks}
                    onOpenTask={openTask}
                    onStopTask={stopTask}
                    onDeleteTask={deleteTask}
                    onOpenFile={setOpenFile}
                    showSnapshots={!isWebDeployment}
                  />
                ) : (
                  <BackgroundTasksPanel
                    tasks={backgroundTasks}
                    onOpen={openTask}
                    onStop={stopTask}
                    onDelete={deleteTask}
                  />
                )}
              </div>
            )}
          </AppShell>
          {!sidebarCollapsed && (
            <div className="fixed bottom-3 left-0 z-30 flex w-[260px] justify-end gap-0.5 px-2">
              <IconButton
                label="Paramètres"
                icon={<GearIcon />}
                variant="ghost"
                size="sm"
                onClick={() => {
                  setSettingsOpen(true);
                }}
              />
              <IconButton
                label={
                  themeMode === "dark"
                    ? "Passer en thème clair"
                    : "Passer en thème sombre"
                }
                icon={themeMode === "dark" ? <MoonIcon /> : <SunIcon />}
                variant="ghost"
                size="sm"
                onClick={toggleTheme}
              />
            </div>
          )}
        </div>
      </div>

      <ImagePreviewDialog
        image={previewImage}
        onOpenChange={(isOpen) => {
          if (!isOpen) setPreviewImage(null);
        }}
        onRequestChange={requestImageChange}
      />

      <AlertDialog
        isOpen={deletingSession !== null}
        onOpenChange={(isOpen) => {
          if (!isOpen) setDeletingSession(null);
        }}
        title="Supprimer la conversation ?"
        description={`« ${deletingSession?.title ?? (deletingSession ? formatSessionLabel(deletingSession.id) : "")} » sera définitivement supprimée. Cette action est irréversible.`}
        actionLabel="Supprimer"
        isActionLoading={isDeleting}
        onAction={confirmDeleteSession}
      />

      {remoteProjectsEnabled && <AlertDialog
        isOpen={deletingProject !== null}
        onOpenChange={(isOpen) => {
          if (!isOpen) setDeletingProject(null);
        }}
        title="Supprimer le projet ?"
        description={`« ${deletingProject?.name ?? ""} » sera supprimé. Ses conversations ne seront pas effacées, mais ne seront plus rattachées au dossier.`}
        actionLabel="Supprimer"
        onAction={confirmDeleteProject}
      />}

      {!isWebDeployment && <AlertDialog
        isOpen={undoTarget !== null}
        onOpenChange={(isOpen) => {
          if (!isOpen) setUndoTarget(null);
        }}
        title="Annuler le dernier message ?"
        description={`Annule les fichiers créés, modifiés ou supprimés depuis le dernier message écrit dans le dossier du projet. Cette action est irréversible.${describeSnapshotDiff(undoDiff)}`}
        actionLabel="Restaurer"
        isActionLoading={undoing}
        onAction={() => {
          void confirmUndo();
        }}
      />}

      <SettingsModal
        isOpen={settingsOpen}
        onClose={() => {
          setSettingsOpen(false);
        }}
        isWebDeployment={isWebDeployment}
        remoteWorkspacesEnabled={remoteProjectsEnabled}
        onModelChanged={refreshApiModel}
        onImageModelChanged={refreshImageModel}
      />

      {remoteProjectsEnabled && <NewProjectModal
        isOpen={showProjectForm}
        onClose={() => {
          setShowProjectForm(false);
        }}
        onCreated={setProjects}
        isWebDeployment={isWebDeployment}
      />}
    </Theme>
  );
}

export default App;
