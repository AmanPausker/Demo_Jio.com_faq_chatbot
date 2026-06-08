import axios from 'axios';
import { supabase } from '../utils/supabaseClient';
import * as FileSystem from 'expo-file-system/legacy';

const API_URL = process.env.EXPO_PUBLIC_API_URL || 'http://10.141.177.237:8000';

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
    const response = await axios.get(`${API_URL}/api/sessions`, { headers });
    return response.data.sessions || [];
  } catch (error) {
    console.error('Failed to fetch sessions:', error);
    return [];
  }
};

export const loadSessionHistory = async (sessionId: string) => {
  try {
    const headers = await getHeaders();
    const response = await axios.get(`${API_URL}/api/sessions/${sessionId}/history`, { headers });
    return response.data.history || [];
  } catch (error) {
    console.error('Failed to load history:', error);
    return [];
  }
};

export const sendChatMessage = async (text: string, sessionId: string | null) => {
  try {
    const headers = await getHeaders();
    const response = await axios.post(`${API_URL}/api/chat`, {
      message: text,
      session_id: sessionId
    }, { headers });
    return response.data;
  } catch (error) {
    console.error('Failed to send message:', error);
    throw error;
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
  } catch (error) {
    console.error('Generate image error', error);
    throw error;
  }
};

export const fetchMemory = async () => {
  try {
    const headers = await getHeaders();
    const response = await axios.get(`${API_URL}/api/memory`, { headers });
    return response.data.memory || 'No long-term memory stored yet.';
  } catch (error) {
    console.error('Failed to fetch memory:', error);
    return 'Failed to load memory.';
  }
};
