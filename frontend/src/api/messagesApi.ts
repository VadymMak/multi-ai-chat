/**
 * Messages API
 * Работа с сообщениями: редактирование, удаление, регенерация
 */

import api from "../services/api";

interface UpdateMessageRequest {
  text: string;
}

interface UpdateMessageResponse {
  success: boolean;
  message: {
    id: string;
    text: string;
    sender: string;
  };
}

interface DeleteMessageResponse {
  success: boolean;
  message: string;
}

interface RegenerateMessageResponse {
  success: boolean;
  message: string;
  todo?: string;
}

/**
 * Редактирование сообщения
 */
export async function updateMessage(
  messageId: string,
  newText: string
): Promise<UpdateMessageResponse> {
  const response = await api.put(`/chat/messages/${messageId}`, {
    text: newText,
  } as UpdateMessageRequest);

  return response.data;
}

/**
 * Удаление сообщения
 */
export async function deleteMessage(
  messageId: string
): Promise<DeleteMessageResponse> {
  const response = await api.delete(`/chat/messages/${messageId}`);
  return response.data;
}

/**
 * Регенерация AI ответа
 */
export async function regenerateMessage(
  messageId: string
): Promise<RegenerateMessageResponse> {
  const response = await api.post(`/chat/messages/${messageId}/regenerate`);
  return response.data;
}
