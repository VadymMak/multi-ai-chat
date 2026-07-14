import { api } from "./api";

export interface Lesson {
  id: number;
  title: string;
  content: string;
  tags: string | null;
  source: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateLesson {
  title: string;
  content: string;
  tags?: string;
  source?: string;
}

export interface UpdateLesson {
  title?: string;
  content?: string;
  tags?: string;
}

export const lessonApi = {
  list: (params?: { q?: string; tag?: string }) =>
    api.get<Lesson[]>("/api/app/lessons", { params }),

  get: (id: number) =>
    api.get<Lesson>(`/api/app/lessons/${id}`),

  create: (data: CreateLesson) =>
    api.post<Lesson>("/api/app/lessons", data),

  update: (id: number, data: UpdateLesson) =>
    api.patch<Lesson>(`/api/app/lessons/${id}`, data),

  remove: (id: number) =>
    api.delete(`/api/app/lessons/${id}`),
};
