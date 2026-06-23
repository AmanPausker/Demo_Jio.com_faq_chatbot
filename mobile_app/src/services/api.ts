import axios from 'axios';
import { supabase } from '../utils/supabaseClient';
import * as FileSystem from 'expo-file-system/legacy';

const API_URL = process.env.EXPO_PUBLIC_API_URL || 'http://10.137.66.237:8000';

const getHeaders = async () => {
  const { data: { session } } = await supabase.auth.getSession();
  return {
    'Content-Type': 'application/json',
    'Authorization': session ? `Bearer ${session.access_token}` : '',
  };
};

export const fetchSessions = async () => {
  try {
    const headers = await getHeaders();
    if (!headers['Authorization']) return [];
    const response = await axios.get(`${API_URL}/api/sessions`, { headers });
    return response.data.sessions || [];
  } catch (error: any) {
    if (error.response?.status === 401) {
      console.warn('Unauthorized: Failed to fetch sessions');
      return [];
    }
    console.error('Failed to fetch sessions:', error);
    return [];
  }
};

export const loadSessionHistory = async (sessionId: string) => {
  try {
    const headers = await getHeaders();
    if (!headers['Authorization']) return [];
    const response = await axios.get(`${API_URL}/api/sessions/${sessionId}/history`, { headers });
    return response.data.history || [];
  } catch (error: any) {
    if (error.response?.status === 401) {
      console.warn('Unauthorized: Failed to load history');
      return [];
    }
    console.error('Failed to load history:', error);
    return [];
  }
};

import EventSource from 'react-native-sse';

export const sendChatMessage = async (text: string, sessionId: string | null, onChunk?: (text: string) => void) => {
  return new Promise(async (resolve, reject) => {
    try {
      const headers = await getHeaders();
      
      const es = new EventSource(`${API_URL}/api/chat`, {
        method: 'POST',
        headers: {
          ...headers,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: text,
          session_id: sessionId
        }),
      });

      es.addEventListener('message', (event) => {
        if (event.data) {
          try {
            const data = JSON.parse(event.data);
            if (data.type === 'token') {
              if (onChunk) onChunk(data.payload);
            } else if (data.type === 'final') {
              es.close();
              resolve(data);
            }
          } catch (e) {
            console.error('SSE JSON parse error', e);
          }
        }
      });

      es.addEventListener('error', (event) => {
        if (event.type === 'error') {
          console.error('SSE error:', event.message);
          es.close();
          if ((event as any).message?.includes('401')) {
            resolve({ text: "Your session has expired. Please log out from the sidebar and log back in." });
          } else {
            reject(new Error(event.message || 'SSE Error'));
          }
        }
      });
    } catch (error: any) {
      if (error.response?.status === 401) {
        console.warn('Unauthorized: Failed to send message');
        resolve({ text: "Your session has expired. Please log out from the sidebar and log back in." });
      } else {
        console.error('Failed to send message:', error);
        reject(error);
      }
    }
  });
};

export const sendAudioMessage = async (audioUri: string, sessionId: string | null) => {
  try {
    const headers = await getHeaders();
    
    const parameters: Record<string, string> = {};
    if (sessionId) {
      parameters['session_id'] = sessionId;
    }
    
    const uploadTask = await FileSystem.uploadAsync(
      `${API_URL}/api/chat/audio`,
      audioUri,
      {
        httpMethod: 'POST',
        uploadType: FileSystem.FileSystemUploadType.MULTIPART,
        fieldName: 'audio',
        headers: {
          'Authorization': headers['Authorization'] || '',
          'Accept': 'application/json'
        },
        parameters
      }
    );
    
    if (uploadTask.status === 401) {
      console.warn('Unauthorized: Failed to send audio');
      return { text: "Your session has expired. Please log out from the sidebar and log back in." };
    }
    if (uploadTask.status !== 200) {
      throw new Error(`HTTP error! status: ${uploadTask.status}`);
    }
    
    return JSON.parse(uploadTask.body);
  } catch (error) {
    console.error('Failed to send audio:', error);
    throw error;
  }
};

export const uploadFile = async (fileUri: string, fileName: string, sessionId: string) => {
  try {
    const headers = await getHeaders();
    
    const parameters: Record<string, string> = {};
    if (sessionId) {
      parameters['session_id'] = sessionId;
    }

    const uploadTask = await FileSystem.uploadAsync(
      `${API_URL}/api/upload`,
      fileUri,
      {
        httpMethod: 'POST',
        uploadType: FileSystem.FileSystemUploadType.MULTIPART,
        fieldName: 'file',
        headers: {
          'Authorization': headers['Authorization'] || '',
          'Accept': 'application/json'
        },
        parameters
      }
    );
    
    if (uploadTask.status === 401) {
      console.warn('Unauthorized: Failed to upload file');
      return { error: "Your session has expired. Please log out and log back in." };
    }
    if (uploadTask.status !== 200) {
      throw new Error(`HTTP error! status: ${uploadTask.status}`);
    }
    
    return JSON.parse(uploadTask.body);
  } catch (error) {
    console.error('Upload error', error);
    throw error;
  }
};

export const generateImage = async (prompt: string) => {
  try {
    const response = await axios.post(`${API_URL}/api/generate_image`, { prompt });
    return response.data;
  } catch (error: any) {
    if (error.response?.status === 401) {
      console.warn('Unauthorized: Failed to generate image');
      return { error: "Your session has expired. Please log out and log back in." };
    }
    console.error('Generate image error', error);
    throw error;
  }
};

