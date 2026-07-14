import axios from 'axios';
import { supabase } from '../utils/supabaseClient';
import * as FileSystem from 'expo-file-system/legacy';
import { generateLocalResponse } from './localLlama';

const API_URL = process.env.EXPO_PUBLIC_API_URL || 'http://10.174.249.237:8000';
import { MEMORY_EVALUATION_PROMPT, STM_SUMMARIZATION_PROMPT } from './prompts';

const runBackgroundTasks = async (userMessage: string, aiMessage: string, sessionId: string, router: string, headers: any) => {
  const tBgStart = Date.now();
  try {
    // Background evaluation and summarization are already triggered automatically 
    // by the backend server when it receives the /api/chat/save_history POST request.
    // Running these on the mobile CPU via generateLocalResponse is redundant and causes severe lag.
    console.log("Skipping mobile background tasks (handled by backend server via save_history).");
  } catch (error) {
    console.error("Background tasks failed:", error);
  }
};

const getHeaders = async () => {
  const tH = Date.now();
  const { data: { session } } = await supabase.auth.getSession();
  const elapsed = Date.now() - tH;
  if (elapsed > 100) console.warn(`[LATENCY] getHeaders (Supabase getSession): ${elapsed}ms`);
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
  const tLoad = Date.now();
  try {
    const headers = await getHeaders();
    if (!headers['Authorization']) return [];
    const response = await axios.get(`${API_URL}/api/sessions/${sessionId}/history`, { headers });
    console.log(`[LATENCY] Mobile loadSessionHistory: ${Date.now() - tLoad}ms`);
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
  const tTotal = Date.now();
  try {
    const headers = await getHeaders();
    
    // Step 1: Hit the Prep Endpoint
    const tPrep = Date.now();
    const prepResponse = await axios.post(`${API_URL}/api/chat/prepare`, {
      message: text,
      session_id: sessionId,
    }, {
      headers: {
        ...headers,
        'Content-Type': 'application/json',
      }
    });
    console.log(`[LATENCY] Mobile POST /api/chat/prepare: ${Date.now() - tPrep}ms`);
    
    // Step 2: Get the Prompt
    const { prompt, context } = prepResponse.data;
    
    // Step 3: Run Local Inference
    const tLocal = Date.now();
    const gemmaPrompt = `<start_of_turn>user\n${prompt}\n\n${text}<end_of_turn>\n<start_of_turn>model\n`;
    let finalAnswer = await generateLocalResponse(gemmaPrompt, (token) => {
      if (onChunk) onChunk(token);
    });
    console.log(`[LATENCY] Mobile local LLM inference: ${Date.now() - tLocal}ms`);
    
    let a2ui_messages: any[] = [];
    let surface_id = `chat_${Date.now()}`;

    // Step 3.5: Intercept leaked JSON tool calls
    const toolRegex = /\{[\s\S]*"(name|tool)"\s*:\s*"get_(weather|current_location)"[\s\S]*\}/;
    const match = finalAnswer.match(toolRegex);
    if (match) {
      try {
        console.log("RAW MATCH:", match[0]);
        const parsed = JSON.parse(match[0]);
        console.log("PARSED JSON:", parsed);
        
        const tool_name = parsed.name || parsed.tool;
        let tool_args = parsed.parameters || parsed.arguments || parsed.param || parsed.params || parsed.args;
        
        if (typeof tool_args === 'string') {
          try { tool_args = JSON.parse(tool_args); } catch(e) {}
        }
        
        if (!tool_args || Object.keys(tool_args).length === 0) {
          tool_args = { ...parsed };
          delete tool_args.name;
          delete tool_args.tool;
          delete tool_args.action;
        }
        
        // Normalize alias for get_weather
        if (tool_name === 'get_weather' && !tool_args.city && tool_args.location) {
          tool_args.city = tool_args.location;
          delete tool_args.location;
        }
        
        console.log("EXTRACTED TOOL ARGS:", tool_args);
        
        // Call backend to execute tool
        const tTool = Date.now();
        const toolResponse = await axios.post(`${API_URL}/api/tools/execute`, {
          tool_name: tool_name,
          tool_args: tool_args
        }, { headers: { ...headers, 'Content-Type': 'application/json' } });
        console.log(`[LATENCY] Mobile tool execution: ${Date.now() - tTool}ms`);
        
        const toolOutput = toolResponse.data.result;
        
        if (toolOutput.includes('WeatherCard')) {
          const weatherData = JSON.parse(toolOutput);
          a2ui_messages = [
            {
              "version": "v0.9",
              "createSurface": {"surfaceId": surface_id, "catalogId": "https://example.com/my-catalog.json"}
            },
            {
              "version": "v0.9",
              "updateComponents": {
                "surfaceId": surface_id,
                "components": [
                  {"id": "root", "component": "WeatherCard", "props": weatherData.props}
                ]
              }
            }
          ];
          finalAnswer = `Here is the weather information for ${weatherData.props.city}.`;
        }
      } catch (e) {
        console.warn("Failed to parse local tool execution:", e);
      }
    }
    
    // Step 4: Sync History to Backend
    const tSync = Date.now();
    try {
      await axios.post(`${API_URL}/api/chat/save_history`, {
        user_message: text,
        ai_message: finalAnswer,
        session_id: sessionId,
        router: prepResponse.data.router?.toString() || "1",
        a2ui_messages: a2ui_messages
      }, {
        headers: { ...headers, 'Content-Type': 'application/json' }
      });
    } catch (e) {
      console.warn("Failed to sync chat history to backend:", e);
    }
    console.log(`[LATENCY] Mobile POST /api/chat/save_history: ${Date.now() - tSync}ms`);
    
    // Step 4.5: Run Background Tasks (fire and forget)
    if (sessionId) {
      runBackgroundTasks(text, finalAnswer, sessionId, prepResponse.data.router?.toString() || "1", headers);
    }
    
    // Step 5: Return 
    console.log(`[LATENCY] Mobile sendChatMessage total: ${Date.now() - tTotal}ms router=${prepResponse.data.router}`);
    return {
      text: finalAnswer,
      session_id: sessionId,
      audio_base64: null,
      a2ui_messages: a2ui_messages,
      surface_id: surface_id
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
  const tAudio = Date.now();
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

    const result = JSON.parse(uploadTask.body);
    console.log(`[LATENCY] Mobile sendAudioMessage: ${Date.now() - tAudio}ms`);
    return result;
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

