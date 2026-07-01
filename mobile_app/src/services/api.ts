import axios from 'axios';
import { supabase } from '../utils/supabaseClient';
import * as FileSystem from 'expo-file-system/legacy';
import { generateLocalResponse } from './localLlama';

const API_URL = process.env.EXPO_PUBLIC_API_URL || 'http://10.169.209.237:8000';

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

export const sendChatMessage = async (text: string, sessionId: string | null, onChunk?: (text: string) => void, imageBase64?: string) => {
  try {
    const headers = await getHeaders();
    
    // Step 1: Hit the Prep Endpoint
    const prepResponse = await axios.post(`${API_URL}/api/chat/prepare`, {
      message: text,
      session_id: sessionId,
    }, {
      headers: {
        ...headers,
        'Content-Type': 'application/json',
      }
    });
    
    // Step 2: Get the Prompt
    const { prompt, context } = prepResponse.data;
    
    // Step 3: Run Local Inference
    const finalAnswer = await generateLocalResponse(prompt + "\n\nUser: " + text, (token) => {
      if (onChunk) onChunk(token);
    });
    
    // Step 4: Return 
    // We mock the properties that the frontend expects from the old API
    return {
      text: finalAnswer,
      session_id: sessionId,
      audio_base64: null,
      a2ui_messages: [], // Real app would extract WeatherCard JSON here
      surface_id: `chat_${Date.now()}`
    };

  } catch (error: any) {
    if (error.response?.status === 401) {
      console.warn('Unauthorized: Failed to send message');
      return { text: "Your session has expired. Please log out from the sidebar and log back in." };
    } else {
      console.error('Failed to send message:', error);
      throw new Error(`Failed: ${error.message || "Unknown error"}`);
    }
  }
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

