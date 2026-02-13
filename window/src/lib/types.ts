/** TypeScript types matching backend WebSocket/REST payloads. */

export interface SceneLayers {
  background: string;
  shop: string;
  items: ShelfItem[];
  character: string;
  character_position: Position;
  foreground: string[];
  weather: string;
  scene_id: string;
}

export interface ShelfItem {
  sprite: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Position {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface TextEntry {
  content: string;
  type: FragmentType;
  timestamp: string;
}

export type FragmentType =
  | 'journal'
  | 'thought'
  | 'thread_update'
  | 'response'
  | 'visitor_speech';

export interface ThreadInfo {
  id: string;
  title: string;
  status: string;
}

export interface WindowState {
  threads: ThreadInfo[];
  weather_diegetic: string;
  time_label: string;
  status: 'awake' | 'sleeping' | 'resting';
  visitor_present: boolean;
}

// ─── WebSocket Messages ───

export interface SceneUpdateMessage {
  type: 'scene_update';
  layers: SceneLayers;
  text: {
    current_thought?: string;
    activity_label?: string;
    recent_entries?: TextEntry[];
  };
  state: WindowState;
  timestamp: string;
}

export interface TextFragmentMessage {
  type: 'text_fragment';
  content: string;
  fragment_type: FragmentType;
  timestamp: string;
}

export interface ItemAddedMessage {
  type: 'item_added';
  item: ShelfItem & { description?: string };
  timestamp: string;
}

export interface StatusMessage {
  type: 'status';
  status: 'awake' | 'sleeping' | 'resting';
  message: string;
}

export interface ChatErrorMessage {
  type: 'chat_error';
  message: string;
}

export type ServerMessage =
  | SceneUpdateMessage
  | TextFragmentMessage
  | ItemAddedMessage
  | StatusMessage
  | ChatErrorMessage;

// ─── Client → Server ───

export interface VisitorMessage {
  type: 'visitor_message';
  text: string;
  token: string;
}

// ─── Aggregated client state ───

export interface ShopkeeperState {
  layers: SceneLayers | null;
  textEntries: TextEntry[];
  windowState: WindowState | null;
  currentThought: string;
  activityLabel: string;
  connected: boolean;
}
