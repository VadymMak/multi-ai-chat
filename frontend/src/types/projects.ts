// src/types/project.ts
export interface ProjectOption {
  id: number;
  name: string;
  description?: string;
}

export interface Assistant {
  id: number;
  name: string;
  description?: string;
}

export interface Project {
  id: number;
  name: string;
  description?: string;
  assistant?: Assistant;
  assistant_id?: number;
  created_at?: string;
  updated_at?: string;
}

export interface ProjectCreate {
  name: string;
  description?: string;
  assistant_id: number;
}

export interface ProjectUpdate {
  name?: string;
  description?: string;
}
