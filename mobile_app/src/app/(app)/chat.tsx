import React, { useState, useEffect, useRef } from 'react';
import { 
  View, Text, TextInput, TouchableOpacity, StyleSheet, 
  FlatList, KeyboardAvoidingView, Platform, Image, ActivityIndicator, Keyboard 
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Audio } from 'expo-av';
import { useLocalSearchParams, useNavigation, useRouter } from 'expo-router';
import { DrawerActions } from '@react-navigation/native';
import * as ImagePicker from 'expo-image-picker';
import * as DocumentPicker from 'expo-document-picker';
import { supabase } from '../../utils/supabaseClient';
import { Feather, MaterialIcons } from '@expo/vector-icons';
import { 
  fetchSessions, loadSessionHistory, sendChatMessage, 
  sendAudioMessage, uploadFile, generateImage 
} from '../../services/api';
import Animated, { useSharedValue, useAnimatedStyle, withRepeat, withTiming, withSequence, Easing, cancelAnimation } from 'react-native-reanimated';
import { LinearGradient } from 'expo-linear-gradient';

function generateUUID() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
    var r = Math.random() * 16 | 0, v = c == 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });
}

export default function ChatScreen() {
  const insets = useSafeAreaInsets();
  const [messages, setMessages] = useState<any[]>([{ id: '1', role: 'bot', text: 'Hello! How can I help you today?' }]);
  const [inputText, setInputText] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [isPlusMenuOpen, setIsPlusMenuOpen] = useState(false);
  const [isKeyboardVisible, setKeyboardVisible] = useState(false);
  const params = useLocalSearchParams();
  const navigation = useNavigation();
  const router = useRouter();

  useEffect(() => {
    if (params.sessionId) {
      setActiveSessionId(params.sessionId as string);
      loadHistory(params.sessionId as string);
    } else {
      handleNewChat();
    }
  }, [params.sessionId, params.newChat]);

  const loadHistory = async (id: string) => {
    setIsLoading(true);
    try {
      const history = await loadSessionHistory(id);
      if (history && history.length > 0) {
        const formattedHistory = history.map((msg: any) => ({
          id: Date.now().toString() + Math.random(),
          role: msg.type === 'user' ? 'user' : 'bot',
          text: msg.content
        }));
        setMessages(formattedHistory);
      } else {
        handleNewChat();
      }
    } catch (e) {
      console.error(e);
      handleNewChat();
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    const keyboardDidShowListener = Keyboard.addListener(
      Platform.OS === 'ios' ? 'keyboardWillShow' : 'keyboardDidShow',
      () => setKeyboardVisible(true)
    );
    const keyboardDidHideListener = Keyboard.addListener(
      Platform.OS === 'ios' ? 'keyboardWillHide' : 'keyboardDidHide',
      () => setKeyboardVisible(false)
    );
    return () => {
      keyboardDidShowListener.remove();
      keyboardDidHideListener.remove();
    };
  }, []);
  
  // Voice Mode State
  const [isVoiceMode, setIsVoiceMode] = useState(false);
  const isVoiceModeRef = useRef(false);
  const [isRecordingVoiceMessage, setIsRecordingVoiceMessage] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const isPlayingRef = useRef(false);
  const recordingRef = useRef<Audio.Recording | null>(null);
  const soundRef = useRef<Audio.Sound | null>(null);

  // VAD logic
  const silenceTimerRef = useRef<NodeJS.Timeout | null>(null);
  const isSpeakingState = useRef(false);
  const VOLUME_THRESHOLD = -20; // dB threshold (increased from -35)
  const SILENCE_MS_TO_STOP = 1500;

  // Animations
  const pulseAnim = useSharedValue(1);
  const pulseStyle = useAnimatedStyle(() => ({
    transform: [{ scale: pulseAnim.value }]
  }));

  useEffect(() => {
    if (isPlaying && isVoiceMode) {
      pulseAnim.value = withRepeat(
        withSequence(withTiming(1.15, { duration: 800 }), withTiming(1, { duration: 800 })),
        -1, true
      );
    } else if (!isPlaying && !isRecording && isVoiceMode) {
      cancelAnimation(pulseAnim);
      pulseAnim.value = withTiming(1, { duration: 300 });
    }
  }, [isPlaying, isRecording, isVoiceMode]);

  useEffect(() => {
    // Only call handleNewChat on initial mount if there is no sessionId
    if (!params.sessionId && !params.newChat) {
      handleNewChat();
    }
    
    // Request permissions
    (async () => {
      await Audio.requestPermissionsAsync();
    })();

    return () => {
      if (recordingRef.current) {
        recordingRef.current.stopAndUnloadAsync().catch(() => {});
      }
      if (soundRef.current) {
        soundRef.current.unloadAsync().catch(() => {});
      }
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
    };
  }, []);

  useEffect(() => {
    isVoiceModeRef.current = isVoiceMode;
    if (isVoiceMode) {
      startVAD();
    } else {
      stopRecording();
    }
  }, [isVoiceMode]);

  const handleNewChat = () => {
    const newSessionId = generateUUID();
    setActiveSessionId(newSessionId);
    setMessages([{ id: Date.now().toString(), role: 'bot', text: 'Hello! How can I help you today?' }]);
    setIsVoiceMode(false);
  };

  const handleSendText = async () => {
    if (!inputText.trim()) return;
    const userMsg = { id: Date.now().toString(), role: 'user', text: inputText };
    setMessages(prev => [...prev, userMsg]);
    setInputText('');
    setIsLoading(true);

    try {
      if (userMsg.text.startsWith('/imagine ')) {
        const prompt = userMsg.text.replace('/imagine ', '');
        const data = await generateImage(prompt);
        if (data.success) {
          setMessages(prev => [...prev, {
            id: Date.now().toString(),
            role: 'bot',
            text: `✨ Here is your image for: "${prompt}"`,
            image: `data:image/jpeg;base64,${data.image_base64}`
          }]);
        }
      } else {
        const data = await sendChatMessage(userMsg.text, activeSessionId);
        
        if (data.session_id && !activeSessionId) {
          setActiveSessionId(data.session_id);
          router.setParams({ sessionId: data.session_id });
        }
        
        let a2uiComponents = null;
        if (data.a2ui_messages && data.a2ui_messages.length > 0) {
          for (const msg of data.a2ui_messages) {
            if (msg.updateComponents) {
              for (const comp of msg.updateComponents.components) {
                if (comp.component === 'WeatherCard') {
                  a2uiComponents = comp;
                }
              }
            }
          }
        }

        setMessages(prev => [...prev, { 
          id: Date.now().toString(), 
          role: 'bot', 
          text: data.text,
          weather: a2uiComponents 
        }]);
        if (data.audio_base64) playAudioBase64(data.audio_base64);
      }
    } catch (e) {
      setMessages(prev => [...prev, { id: Date.now().toString(), role: 'bot', text: 'Sorry, I encountered an error.' }]);
    } finally {
      setIsLoading(false);
    }
  };

  const playAudioBase64 = async (base64String: string) => {
    try {
      if (soundRef.current) await soundRef.current.unloadAsync();
      const { sound } = await Audio.Sound.createAsync({ uri: `data:audio/wav;base64,${base64String}` });
      soundRef.current = sound;
      
      sound.setOnPlaybackStatusUpdate((status: any) => {
        if (status.didJustFinish) {
          setIsPlaying(false);
          isPlayingRef.current = false;
        }
      });
      
      setIsPlaying(true);
      isPlayingRef.current = true;
      await sound.playAsync();
    } catch (e) {
      console.error('Playback error', e);
      setIsPlaying(false);
      isPlayingRef.current = false;
    }
  };

  const startVAD = async () => {
    try {
      if (recordingRef.current) {
        try {
          await recordingRef.current.stopAndUnloadAsync();
        } catch (e) {}
        recordingRef.current = null;
      }

      await Audio.setAudioModeAsync({
        allowsRecordingIOS: true,
        playsInSilentModeIOS: true,
      });

      const { recording } = await Audio.Recording.createAsync(
        Audio.RecordingOptionsPresets.HIGH_QUALITY,
        (status) => {
          if (status.metering) {
            handleMetering(status.metering);
          }
        },
        100 // polling interval
      );
      recordingRef.current = recording;
      
    } catch (err) {
      console.error('Failed to start VAD recording', err);
    }
  };

  const handleMetering = (db: number) => {
    if (!isPlayingRef.current) {
      const scale = 1 + (Math.max(0, db + 60) / 60) * 0.4;
      pulseAnim.value = withTiming(scale, { duration: 100, easing: Easing.linear });
    }

    if (db > VOLUME_THRESHOLD) {
      if (silenceTimerRef.current) {
        clearTimeout(silenceTimerRef.current);
        silenceTimerRef.current = null;
      }
      if (!isSpeakingState.current) {
        isSpeakingState.current = true;
        setIsRecording(true);
        if (soundRef.current && isPlayingRef.current) {
          soundRef.current.stopAsync().catch(() => {});
          setIsPlaying(false);
          isPlayingRef.current = false;
        }
      }
    } else {
      if (isSpeakingState.current && !silenceTimerRef.current) {
        silenceTimerRef.current = setTimeout(() => {
          isSpeakingState.current = false;
          handleSpeechEnd();
        }, SILENCE_MS_TO_STOP);
      }
    }
  };

  const handleSpeechEnd = async () => {
    setIsRecording(false);
    if (!recordingRef.current) return;
    try {
      await recordingRef.current.stopAndUnloadAsync();
      const uri = recordingRef.current.getURI();
      recordingRef.current = null;
      if (uri) await sendAudioToServer(uri, false);
      
      // Restart listening after sending
      if (isVoiceModeRef.current) startVAD();
    } catch (e) {
      console.error('Stop recording error', e);
    }
  };

  const stopRecording = async () => {
    setIsRecording(false);
    isSpeakingState.current = false;
    cancelAnimation(pulseAnim);
    if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
    if (soundRef.current) {
      soundRef.current.stopAsync().catch(() => {});
      setIsPlaying(false);
      isPlayingRef.current = false;
    }
    if (recordingRef.current) {
      try {
        await recordingRef.current.stopAndUnloadAsync();
      } catch (e) {
        // Ignore if already unloaded
      }
      recordingRef.current = null;
    }
  };

  const startVoiceMessage = async () => {
    try {
      if (recordingRef.current) {
        try {
          await recordingRef.current.stopAndUnloadAsync();
        } catch (e) {}
        recordingRef.current = null;
      }

      await Audio.setAudioModeAsync({
        allowsRecordingIOS: true,
        playsInSilentModeIOS: true,
      });

      const { recording } = await Audio.Recording.createAsync(
        Audio.RecordingOptionsPresets.HIGH_QUALITY
      );
      recordingRef.current = recording;
      setIsRecordingVoiceMessage(true);
    } catch (err) {
      console.error('Failed to start voice message recording', err);
    }
  };

  const sendVoiceMessage = async () => {
    setIsRecordingVoiceMessage(false);
    if (!recordingRef.current) return;
    try {
      await recordingRef.current.stopAndUnloadAsync();
      const uri = recordingRef.current.getURI();
      recordingRef.current = null;
      if (uri) await sendAudioToServer(uri, true);
    } catch (e) {
      console.error('Send voice message error', e);
    }
  };

  const cancelVoiceMessage = async () => {
    setIsRecordingVoiceMessage(false);
    if (!recordingRef.current) return;
    try {
      await recordingRef.current.stopAndUnloadAsync();
      recordingRef.current = null;
    } catch (e) {
      console.error('Cancel voice message error', e);
    }
  };

  const sendAudioToServer = async (uri: string, isManual = false) => {
    setIsLoading(true);
    try {
      const data = await sendAudioMessage(uri, activeSessionId);
      
      if (data.session_id && !activeSessionId) {
        setActiveSessionId(data.session_id);
        router.setParams({ sessionId: data.session_id });
      }
      
      if (data.user_message) {
        setMessages(prev => [...prev, { id: Date.now().toString()+'u', role: 'user', text: `🎤 ${data.user_message}` }]);
      }
      
      let a2uiComponents = null;
      if (data.a2ui_messages && data.a2ui_messages.length > 0) {
        for (const msg of data.a2ui_messages) {
          if (msg.updateComponents) {
            for (const comp of msg.updateComponents.components) {
              if (comp.component === 'WeatherCard') {
                a2uiComponents = comp;
              }
            }
          }
        }
      }

      setMessages(prev => [...prev, { 
        id: Date.now().toString()+'b', 
        role: 'bot', 
        text: data.text,
        weather: a2uiComponents
      }]);
      
      if (data.audio_base64) {
        if (isManual || isVoiceModeRef.current) {
          playAudioBase64(data.audio_base64);
        }
      }
    } catch (error) {
      console.error('Send audio error:', error);
    } finally {
      setIsLoading(false);
    }
  };



  const pickDocument = async () => {
    let result = await DocumentPicker.getDocumentAsync({ type: 'application/pdf' });
    if (!result.canceled) {
      const file = result.assets[0];
      setMessages(prev => [...prev, { id: Date.now().toString(), role: 'user', text: `📄 Uploaded PDF: ${file.name}` }]);
      try {
        setIsLoading(true);
        let sessionIdToUse = activeSessionId;
        if (!sessionIdToUse) {
          sessionIdToUse = generateUUID();
          setActiveSessionId(sessionIdToUse);
          router.setParams({ sessionId: sessionIdToUse });
        }
        const res = await uploadFile(file.uri, file.name, sessionIdToUse);
        setMessages(prev => [...prev, { id: Date.now().toString(), role: 'bot', text: res.message }]);
      } catch (e) {
        setMessages(prev => [...prev, { id: Date.now().toString(), role: 'bot', text: 'Upload failed.' }]);
      } finally {
        setIsLoading(false);
      }
    }
  };

  const renderMessage = ({ item }: { item: any }) => {
    const getWeatherIcon = (condition: string) => {
      const c = condition?.toLowerCase() || '';
      if (c.includes('rain') || c.includes('drizzle')) return '🌧️';
      if (c.includes('cloud')) return '☁️';
      if (c.includes('clear') || c.includes('sun')) return '☀️';
      if (c.includes('snow')) return '❄️';
      if (c.includes('haze') || c.includes('fog') || c.includes('mist')) return '🌫️';
      if (c.includes('thunder') || c.includes('storm')) return '⛈️';
      return '🌡️';
    };

    return (
      <View style={[styles.messageWrapper, item.role === 'user' ? styles.messageUser : styles.messageBot]}>
        <View style={[styles.messageBubble, item.role === 'user' ? styles.bubbleUser : styles.bubbleBot]}>
          <Text style={styles.messageText}>{item.text}</Text>
          {item.image && <Image source={{ uri: item.image }} style={styles.messageImage} />}
          {item.weather && (
            <View style={styles.weatherCard}>
              <View style={styles.weatherHeader}>
                <Text style={styles.weatherCity}>{item.weather.city}</Text>
                <Text style={styles.weatherIcon}>{getWeatherIcon(item.weather.condition)}</Text>
              </View>
              <View style={{flexDirection: 'row', alignItems: 'baseline', marginTop: 10}}>
                <Text style={styles.weatherTemp}>{item.weather.temperature}</Text>
                <Text style={styles.weatherTempUnit}>°C</Text>
              </View>
              <Text style={styles.weatherCondition}>{item.weather.condition?.toUpperCase()}</Text>
            </View>
          )}
        </View>
      </View>
    );
  };

  return (
    <View style={[styles.container, { paddingTop: insets.top }]}>
      <KeyboardAvoidingView 
        style={{ flex: 1 }} 
        behavior="padding"
      >
        {!isVoiceMode && (
          <View style={styles.header}>
            <TouchableOpacity onPress={() => navigation.dispatch(DrawerActions.openDrawer())}>
              <Feather name="menu" size={24} color="#fff" />
            </TouchableOpacity>
            <Text style={styles.headerTitle}>Jio FAQ Chatbot</Text>
            <TouchableOpacity onPress={() => supabase.auth.signOut()}>
              <Text style={styles.logoutText}>Logout</Text>
            </TouchableOpacity>
          </View>
        )}

      {isVoiceMode ? (
        <View style={styles.voiceContainer}>
          <View style={styles.voiceTopBar}>
            <TouchableOpacity onPress={() => setIsVoiceMode(false)} style={styles.voiceIconBtn}>
              <Feather name="arrow-left" size={24} color="#ffffff" />
            </TouchableOpacity>
            <View style={styles.sparkleCircle}>
              <MaterialIcons name="auto-awesome" size={20} color="#ffffff" />
            </View>
          </View>
          
          <View style={styles.voiceCenter}>
            <View style={styles.liveTextContainer}>
              <Text style={styles.liveText} numberOfLines={8} adjustsFontSizeToFit>
                {messages[messages.length - 1]?.text?.replace('🎤 ', '') || "Ask anything..."}
              </Text>
            </View>

            <Text style={styles.voiceStatus}>
              {isPlaying ? 'AI is speaking...' : isLoading ? 'Thinking...' : isRecording ? 'Listening...' : 'Speak freely...'}
            </Text>
            
            <View style={styles.orbWrapper}>
              <Animated.View style={[styles.glowAura, pulseStyle]} />
              <LinearGradient
                colors={['#d946ef', '#a855f7', '#fbbf24']}
                start={{ x: 0.1, y: 0.1 }}
                end={{ x: 0.9, y: 0.9 }}
                style={styles.voiceOrb}
              >
                <Feather name="mic" size={44} color="#ffffff" />
              </LinearGradient>
            </View>
          </View>
        </View>
      ) : (
        <>
          <FlatList
            data={messages}
            keyExtractor={item => item.id}
            renderItem={renderMessage}
            contentContainerStyle={styles.listContent}
          />
          
          {isLoading && <ActivityIndicator size="small" color="#007bff" style={{ margin: 10 }} />}

          {isPlusMenuOpen && (
            <View style={styles.plusMenu}>
              <TouchableOpacity style={styles.menuItem} onPress={() => { setIsPlusMenuOpen(false); pickDocument(); }}>
                <Feather name="file-text" size={20} color="#a855f7" />
                <Text style={styles.menuText}>Upload Document</Text>
              </TouchableOpacity>
            </View>
          )}

          <View style={[styles.inputArea, { paddingBottom: isKeyboardVisible ? 12 : Math.max(insets.bottom, 12) }]}>
            {isRecordingVoiceMessage ? (
              <View style={styles.voiceMessageBar}>
                <TouchableOpacity style={styles.iconBtn} onPress={cancelVoiceMessage}>
                  <Feather name="trash-2" size={22} color="#ef4444" />
                </TouchableOpacity>
                <Text style={styles.recordingText}>Recording...</Text>
                <TouchableOpacity style={styles.sendBtn} onPress={sendVoiceMessage}>
                  <Feather name="arrow-up" size={20} color="#fff" />
                </TouchableOpacity>
              </View>
            ) : (
              <>
                <TouchableOpacity style={styles.iconBtn} onPress={() => setIsPlusMenuOpen(!isPlusMenuOpen)}>
                  <Feather name="plus" size={24} color="#a1a1aa" />
                </TouchableOpacity>
                
                <TextInput
                  style={styles.input}
                  placeholder="Message..."
                  placeholderTextColor="#a1a1aa"
                  value={inputText}
                  onChangeText={setInputText}
                  onSubmitEditing={handleSendText}
                />
                
                {inputText.length === 0 ? (
                  <>
                    <TouchableOpacity style={styles.iconBtn} onPress={startVoiceMessage}>
                      <Feather name="mic" size={22} color="#a1a1aa" />
                    </TouchableOpacity>
                    <TouchableOpacity style={styles.iconBtn} onPress={() => setIsVoiceMode(true)}>
                      <MaterialIcons name="graphic-eq" size={24} color="#a1a1aa" />
                    </TouchableOpacity>
                    <TouchableOpacity style={styles.iconBtn} onPress={() => router.push({ pathname: '/live' })}>
                      <Feather name="video" size={24} color="#a1a1aa" />
                    </TouchableOpacity>
                  </>
                ) : (
                  <TouchableOpacity style={styles.sendBtn} onPress={handleSendText}>
                    <Feather name="arrow-up" size={20} color="#fff" />
                  </TouchableOpacity>
                )}
              </>
            )}
          </View>
        </>
      )}
      </KeyboardAvoidingView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#09090b',
  },
  header: {
    paddingTop: 15,
    paddingBottom: 15,
    paddingHorizontal: 20,
    backgroundColor: '#18181b',
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    borderBottomWidth: 1,
    borderBottomColor: '#27272a',
  },
  headerTitle: {
    color: '#fff',
    fontSize: 18,
    fontWeight: 'bold',
  },
  logoutText: {
    color: '#ef4444',
  },
  listContent: {
    padding: 15,
  },
  messageWrapper: {
    marginBottom: 15,
    flexDirection: 'row',
  },
  messageUser: {
    justifyContent: 'flex-end',
  },
  messageBot: {
    justifyContent: 'flex-start',
  },
  messageBubble: {
    maxWidth: '80%',
    padding: 12,
    borderRadius: 18,
  },
  bubbleUser: {
    backgroundColor: '#007bff',
    borderBottomRightRadius: 4,
  },
  bubbleBot: {
    backgroundColor: '#27272a',
    borderBottomLeftRadius: 4,
  },
  messageText: {
    color: '#fff',
    fontSize: 16,
    lineHeight: 22,
  },
  messageImage: {
    width: 250,
    height: 250,
    borderRadius: 12,
    marginTop: 8,
  },
  inputArea: {
    flexDirection: 'row',
    padding: 12,
    paddingBottom: Platform.OS === 'ios' ? 24 : 12,
    backgroundColor: '#18181b',
    alignItems: 'center',
  },
  input: {
    flex: 1,
    backgroundColor: '#27272a',
    color: '#fff',
    borderRadius: 20,
    paddingHorizontal: 16,
    paddingVertical: 10,
    fontSize: 16,
    marginHorizontal: 8,
    maxHeight: 100,
  },
  iconBtn: {
    padding: 8,
  },
  iconTxt: {
    fontSize: 22,
  },
  sendBtn: {
    backgroundColor: '#007bff',
    width: 36,
    height: 36,
    borderRadius: 18,
    justifyContent: 'center',
    alignItems: 'center',
    marginLeft: 8,
  },
  voiceContainer: {
    flex: 1,
    backgroundColor: '#000000',
  },
  voiceTopBar: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingTop: 10,
    width: '100%',
  },
  voiceIconBtn: {
    padding: 12,
    backgroundColor: 'rgba(255,255,255,0.1)',
    borderRadius: 24,
  },
  sparkleCircle: {
    padding: 12,
    backgroundColor: 'rgba(255,255,255,0.1)',
    borderRadius: 24,
  },
  voiceCenter: {
    flex: 1,
    justifyContent: 'flex-end',
    alignItems: 'center',
    paddingBottom: 80,
    width: '100%',
  },
  liveTextContainer: {
    width: '100%',
    paddingHorizontal: 30,
    marginBottom: 40,
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  liveText: {
    color: '#fdf4ff',
    fontSize: 28,
    lineHeight: 40,
    textAlign: 'center',
    fontWeight: '600',
    textShadowColor: 'rgba(192, 132, 252, 0.6)',
    textShadowOffset: { width: 0, height: 2 },
    textShadowRadius: 15,
  },
  voiceStatus: {
    color: '#a1a1aa',
    fontSize: 16,
    marginBottom: 30,
    letterSpacing: 0.5,
  },
  orbWrapper: {
    width: 140,
    height: 140,
    justifyContent: 'center',
    alignItems: 'center',
  },
  glowAura: {
    position: 'absolute',
    width: 180,
    height: 180,
    borderRadius: 90,
    backgroundColor: 'rgba(192, 132, 252, 0.25)',
    shadowColor: '#c084fc',
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.8,
    shadowRadius: 40,
    elevation: 10,
  },
  voiceOrb: {
    width: 120,
    height: 120,
    borderRadius: 60,
    justifyContent: 'center',
    alignItems: 'center',
    zIndex: 2,
    shadowColor: '#d946ef',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.5,
    shadowRadius: 15,
    elevation: 8,
  },
  plusMenu: {
    position: 'absolute',
    bottom: 80,
    left: 12,
    backgroundColor: '#18181b',
    borderRadius: 16,
    padding: 8,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.1)',
    zIndex: 100,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.5,
    shadowRadius: 15,
    elevation: 10,
  },
  menuItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 12,
  },
  menuText: {
    color: '#e4e4e7',
    fontSize: 16,
    fontWeight: '500',
    marginLeft: 12,
  },
  weatherCard: {
    backgroundColor: 'rgba(37, 99, 235, 0.15)',
    borderRadius: 16,
    padding: 20,
    marginTop: 12,
    borderWidth: 1,
    borderColor: 'rgba(59, 130, 246, 0.3)',
    width: 220,
  },
  weatherHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  weatherCity: {
    color: '#e4e4e7',
    fontSize: 18,
    fontWeight: '600',
  },
  weatherIcon: {
    fontSize: 28,
  },
  weatherTemp: {
    color: '#ffffff',
    fontSize: 54,
    fontWeight: 'bold',
  },
  weatherTempUnit: {
    color: '#60a5fa',
    fontSize: 24,
    fontWeight: 'bold',
    marginLeft: 4,
  },
  weatherCondition: {
    color: '#9ca3af',
    fontSize: 14,
    fontWeight: '600',
    marginTop: 8,
    letterSpacing: 2,
  },
  voiceMessageBar: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: '#27272a',
    borderRadius: 20,
    paddingHorizontal: 16,
    paddingVertical: 8,
    marginHorizontal: 8,
  },
  recordingText: {
    color: '#ef4444',
    fontWeight: 'bold',
    fontSize: 16,
    flex: 1,
    textAlign: 'center',
  },
});
