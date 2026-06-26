import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet,
  FlatList, KeyboardAvoidingView, Platform, ActivityIndicator, Keyboard, AppState, Modal, ScrollView
} from 'react-native';
import { Image } from 'expo-image';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Audio } from 'expo-av';
import { RTCPeerConnection, RTCSessionDescription, mediaDevices } from 'react-native-webrtc';
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
import Animated, { useSharedValue, useAnimatedStyle, withRepeat, withTiming, withSequence, Easing, cancelAnimation, interpolateColor } from 'react-native-reanimated';
import { LinearGradient } from 'expo-linear-gradient';

function generateUUID() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
    var r = Math.random() * 16 | 0, v = c == 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });
}

const MessageItem = React.memo(({ item }: { item: any }) => {
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
        {(!item.weather && item.text.includes('"type"')) ? (
          <Text style={[styles.messageText, { fontStyle: 'italic', color: '#a1a1aa' }]}>Generating widget...</Text>
        ) : (
          <Text style={styles.messageText}>
            {item.text.includes('{"type":') ? item.text.split('{"type":')[0].trim() : item.text}
          </Text>
        )}
        {item.image && <Image source={{ uri: item.image }} style={styles.messageImage} contentFit="cover" />}
        {item.weather && (
          <View style={styles.weatherCard}>
            <View style={styles.weatherHeader}>
              <Text style={styles.weatherCity}>{item.weather.city}</Text>
              <Text style={styles.weatherIcon}>{getWeatherIcon(item.weather.condition)}</Text>
            </View>
            <View style={{ flexDirection: 'row', alignItems: 'baseline', marginTop: 10 }}>
              <Text style={styles.weatherTemp}>{item.weather.temperature}</Text>
              <Text style={styles.weatherTempUnit}>°C</Text>
            </View>
            <Text style={styles.weatherCondition}>{item.weather.condition?.toUpperCase()}</Text>
          </View>
        )}
      </View>
    </View>
  );
});

export default function ChatScreen() {
  const [loadingText, setLoadingText] = useState('Thinking...');

  const [isAccountModalOpen, setIsAccountModalOpen] = useState(false);
  const [userId, setUserId] = useState<string | null>(null);
  const [userMemories, setUserMemories] = useState<string[]>([]);
  const [isLoadingMemories, setIsLoadingMemories] = useState(false);

  const openAccountModal = async () => {
    setIsAccountModalOpen(true);
    setIsLoadingMemories(true);
    try {
      const { data: { user } } = await supabase.auth.getUser();
      if (user) {
        setUserId(user.email || user.id);
        const { data, error } = await supabase.from('user_memory').select('facts').eq('user_id', user.id).single();
        if (data && data.facts) {
          setUserMemories(data.facts);
        } else {
          setUserMemories([]);
        }
      }
    } catch (e) {
      console.log('Error fetching memories', e);
    } finally {
      setIsLoadingMemories(false);
    }
  };

  const colorIndex = useSharedValue(0);
  const animatedBorderStyle = useAnimatedStyle(() => {
    return {
      backgroundColor: interpolateColor(
        colorIndex.value,
        [0, 1, 2],
        ['#3b82f6', '#a855f7', '#ec4899']
      )
    };
  });

  useEffect(() => {
    colorIndex.value = withRepeat(
      withTiming(2, { duration: 4000, easing: Easing.inOut(Easing.ease) }),
      -1,
      true
    );
  }, []);

  // State variable to hold the filler text.
  const [fillerText, setFillerText] = useState("");
  const insets = useSafeAreaInsets();
  const [messages, setMessages] = useState<any[]>([]);
  const [inputText, setInputText] = useState('');
  const [selectedImage, setSelectedImage] = useState<ImagePicker.ImagePickerAsset | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const activeSessionIdRef = useRef<string | null>(null);
  const [isPlusMenuOpen, setIsPlusMenuOpen] = useState(false);
  const [isKeyboardVisible, setKeyboardVisible] = useState(false);
  const params = useLocalSearchParams();
  const navigation = useNavigation();
  const router = useRouter();
  // Add this useEffect right below your other useEffects
  useEffect(() => {
    if (isLoading) {
      const phrases = [
        'Thinking...', 'Analyzing request...', 'Formulating response...', 'Processing input...',
        'Evaluating context...', 'Generating text...', 'Retrieving data...', 'Synthesizing information...',
        'Connecting concepts...', 'Drafting reply...', 'Checking logic...', 'Reviewing parameters...',
        'Parsing intent...', 'Calculating probabilities...', 'Structuring answer...', 'Decoding message...',
        'Aligning knowledge base...', 'Cross-referencing memory...', 'Extracting key points...', 'Refining language...',
        'Polishing syntax...', 'Optimizing tone...', 'Searching archives...', 'Scanning databases...',
        'Correlating facts...', 'Assembling variables...', 'Constructing logic gates...', 'Evaluating pathways...',
        'Simulating outcomes...', 'Translating thoughts...', 'Balancing algorithms...', 'Computing response...',
        'Interpreting query...', 'Weighing options...', 'Calibrating context...', 'Filtering noise...',
        'Isolating signals...', 'Mapping connections...', 'Navigating knowledge graph...', 'Validating hypotheses...',
        'Compiling data...', 'Structuring narrative...', 'Formatting output...', 'Applying heuristics...',
        'Inferring meaning...', 'Deducing answer...', 'Reasoning through prompt...', 'Distilling concepts...',
        'Abstracting details...', 'Summarizing thoughts...', 'Gathering insights...', 'Activating neural pathways...',
        'Running diagnostics...', 'Checking heuristics...', 'Verifying statements...', 'Analyzing semantics...',
        'Deconstructing query...', 'Reconstructing context...', 'Formulating hypothesis...', 'Generating possibilities...',
        'Selecting optimal response...', 'Drafting logic...', 'Evaluating coherence...', 'Checking consistency...',
        'Ensuring accuracy...', 'Validating sources...', 'Structuring arguments...', 'Weighing evidence...',
        'Formulating conclusion...', 'Polishing draft...', 'Refining nuances...', 'Adjusting parameters...',
        'Optimizing clarity...', 'Enhancing readability...', 'Checking constraints...', 'Verifying limits...',
        'Applying logic...', 'Reasoning...', 'Pondering...', 'Deliberating...', 'Contemplating...',
        'Considering...', 'Reflecting...', 'Analyzing...', 'Processing...', 'Computing...',
        'Calculating...', 'Evaluating...', 'Assessing...', 'Reviewing...', 'Checking...',
        'Verifying...', 'Validating...', 'Correlating...', 'Synthesizing...', 'Integrating...',
        'Connecting...', 'Structuring...', 'Formatting...', 'Finalizing...'
      ];
      let timeout: NodeJS.Timeout;
      const cyclePhrase = () => {
        const randomIndex = Math.floor(Math.random() * phrases.length);
        setLoadingText(phrases[randomIndex]);
        const nextDuration = Math.floor(Math.random() * 3000) + 2000; // 2 to 5 seconds
        timeout = setTimeout(cyclePhrase, nextDuration);
      };
      const firstDuration = Math.floor(Math.random() * 2000) + 1000;
      timeout = setTimeout(cyclePhrase, firstDuration);
      return () => clearTimeout(timeout);
    }
  }, [isLoading]);
  useEffect(() => {
    if (params.sessionId) {
      setActiveSessionId(params.sessionId as string);
      activeSessionIdRef.current = params.sessionId as string;
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
        const formattedHistory = history.map((msg: any) => {
          let a2uiComponents = null;
          if (msg.a2ui_messages && msg.a2ui_messages.length > 0) {
            for (const a2ui of msg.a2ui_messages) {
              if (a2ui.updateComponents) {
                for (const comp of a2ui.updateComponents.components) {
                  if (comp.component === 'WeatherCard') {
                    a2uiComponents = comp.props;
                  }
                }
              }
            }
          }
          return {
            id: Date.now().toString() + Math.random(),
            role: msg.type === 'user' ? 'user' : 'bot',
            text: msg.content,
            weather: a2uiComponents
          };
        });
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

  // WebRTC refs
  const wsRef = useRef<WebSocket | null>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const localStreamRef = useRef<any>(null);
  const audioLevelIntervalRef = useRef<NodeJS.Timeout | null>(null);

  // VAD logic
  const silenceTimerRef = useRef<NodeJS.Timeout | null>(null);
  const isSpeakingState = useRef(false);
  const VOLUME_THRESHOLD = -25;
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

    const appStateSubscription = AppState.addEventListener('change', nextAppState => {
      if (nextAppState === 'background' || nextAppState === 'inactive') {
        stopWebRTC();
        setIsVoiceMode(false);
      }
    });

    return () => {
      if (recordingRef.current) {
        recordingRef.current.stopAndUnloadAsync().catch(() => { });
      }
      if (soundRef.current) {
        soundRef.current.unloadAsync().catch(() => { });
      }
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
      stopWebRTC();
      appStateSubscription.remove();
    };
  }, []);

  useEffect(() => {
    isVoiceModeRef.current = isVoiceMode;
    if (isVoiceMode) {
      startWebRTC();
    } else {
      stopWebRTC();
    }
  }, [isVoiceMode]);

  const handleNewChat = () => {
    const newSessionId = generateUUID();
    setActiveSessionId(newSessionId);
    activeSessionIdRef.current = newSessionId;
    setMessages([]);
    setIsVoiceMode(false);
    setIsLoading(false);
  };

  const handleSendText = async () => {
    if (!inputText.trim() && !selectedImage) return;
    const currentImage = selectedImage;
    const currentText = inputText.trim() || (currentImage ? "Describe this image." : "");
    const userMsg = {
      id: Date.now().toString(),
      role: 'user',
      text: currentText,
      ...(currentImage && { image: `data:image/jpeg;base64,${currentImage.base64}` })
    };
    setMessages(prev => [...prev, userMsg]);
    setInputText('');
    setSelectedImage(null);
    setIsLoading(true);

    const currentSessionId = activeSessionIdRef.current;

    try {
      if (userMsg.text.startsWith('/imagine ')) {
        const prompt = userMsg.text.replace('/imagine ', '');
        const data = await generateImage(prompt);
        if (activeSessionIdRef.current !== currentSessionId) return;
        if (data.success) {
          setMessages(prev => [...prev, {
            id: Date.now().toString(),
            role: 'bot',
            text: `✨ Here is your image for: "${prompt}"`,
            image: `data:image/jpeg;base64,${data.image_base64}`
          }]);
        }
      } else {
        const botMessageId = Date.now().toString() + 'b';
        setMessages(prev => [...prev, { id: botMessageId, role: 'bot', text: '' }]);
        // Keep isLoading true or false depending on how we want the UI. Actually, streaming text is already replacing the spinner.
        // We'll leave isLoading true so the user knows it's working, but the text will stream in real-time.

        const data: any = await sendChatMessage(userMsg.text, activeSessionId, (chunk) => {
          setMessages(prev => prev.map(m => {
            if (m.id === botMessageId) {
              return { ...m, text: m.text + chunk };
            }
            return m;
          }));
        }, currentImage?.base64);

        if (activeSessionIdRef.current !== currentSessionId) return;

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
                  a2uiComponents = comp.props;
                }
              }
            }
          }
        }

        setMessages(prev => prev.map(m => {
          if (m.id === botMessageId) {
            return {
              ...m,
              text: data.text,
              weather: a2uiComponents
            };
          }
          return m;
        }));
        if (data.audio_base64) playAudioBase64(data.audio_base64);
      }
    } catch (e) {
      setMessages(prev => [...prev, { id: Date.now().toString(), role: 'bot', text: 'Sorry, I encountered an error.' }]);
    } finally {
      setIsLoading(false);
    }
  };

  const startWebRTC = async () => {
    try {
      await Audio.setAudioModeAsync({
        allowsRecordingIOS: true,
        playsInSilentModeIOS: true,
        staysActiveInBackground: true,
        shouldDuckAndroid: true,
        playThroughEarpieceAndroid: false,
      });
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;

      const wsUrl = (process.env.EXPO_PUBLIC_API_URL || 'http://10.169.209.237:8000').replace('http', 'ws') + '/api/live/ws';
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = async () => {
        ws.send(JSON.stringify({
          type: "auth",
          payload: { token: session.access_token, session_id: activeSessionIdRef.current || params.sessionId }
        }));

        const pc = new RTCPeerConnection({ iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] });
        pcRef.current = pc;

        const stream = await mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true }, video: false });
        localStreamRef.current = stream;

        stream.getTracks().forEach((track: any) => pc.addTrack(track, stream));

        const offer = await pc.createOffer({});
        await pc.setLocalDescription(offer);

        await new Promise<void>((resolve) => {
          if (pc.iceGatheringState === 'complete') {
            resolve();
          } else {
            const timeout = setTimeout(() => resolve(), 2000);
            pc.onicegatheringstatechange = () => {
              if (pc.iceGatheringState === 'complete') {
                clearTimeout(timeout);
                resolve();
              }
            };
          }
        });

        ws.send(JSON.stringify({ type: "webrtc_offer", payload: pc.localDescription }));

      };

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'filler_word') {
          setFillerText(data.payload);
        }
        else if (data.type === 'webrtc_answer') {
          pcRef.current?.setRemoteDescription(new RTCSessionDescription(data.payload));
        }
        else if (data.type === 'assistant_response') {
          setFillerText(""); // Clear filler text
          setMessages(prev => [...prev, { role: 'bot', text: data.payload, id: Date.now().toString() }]);
          setIsPlaying(true);
          setTimeout(() => setIsPlaying(false), 4000);
        } else if (data.type === 'transcript') {
          setMessages(prev => [...prev, { role: 'user', text: `🎤 ${data.payload}`, id: Date.now().toString() }]);
        } else if (data.type === 'user_speaking_start') {
          setFillerText(""); // Clear filler text on user barge-in
          setIsRecording(true);
          isSpeakingState.current = true;
        } else if (data.type === 'user_speaking_end') {
          setIsRecording(false);
          isSpeakingState.current = false;
        }
      };

      ws.onclose = () => {
        console.log('WebRTC WebSocket closed');
        stopWebRTC();
      };
    } catch (err) {
      console.error('Failed to start WebRTC', err);
    }
  };

  const handleInterrupt = () => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "interrupt" }));
    }
  };

  const stopWebRTC = () => {
    setIsRecording(false);
    isSpeakingState.current = false;
    cancelAnimation(pulseAnim);
    if (audioLevelIntervalRef.current) clearInterval(audioLevelIntervalRef.current);
    if (localStreamRef.current) {
      localStreamRef.current.getTracks().forEach((t: any) => t.stop());
      localStreamRef.current = null;
    }
    if (pcRef.current) {
      pcRef.current.close();
      pcRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setIsPlaying(false);
    isPlayingRef.current = false;
  };

  // Drive the orb animation purely based on state instead of raw volume DB
  useEffect(() => {
    if (isRecording || isPlaying) {
      pulseAnim.value = withRepeat(
        withSequence(
          withTiming(1.3, { duration: 400 }),
          withTiming(1.0, { duration: 400 })
        ),
        -1,
        true
      );
    } else {
      pulseAnim.value = withTiming(1.0, { duration: 200 });
    }
  }, [isRecording, isPlaying]);

  const startVoiceMessage = async () => {
    try {
      if (recordingRef.current) {
        try {
          await recordingRef.current.stopAndUnloadAsync();
        } catch (e) { }
        recordingRef.current = null;
      }

      await Audio.setAudioModeAsync({
        allowsRecordingIOS: true,
        playsInSilentModeIOS: true,
        staysActiveInBackground: true,
        shouldDuckAndroid: true,
        playThroughEarpieceAndroid: false,
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
        setMessages(prev => [...prev, { id: Date.now().toString() + 'u', role: 'user', text: `🎤 ${data.user_message}` }]);
      }

      let a2uiComponents = null;
      if (data.a2ui_messages && data.a2ui_messages.length > 0) {
        for (const msg of data.a2ui_messages) {
          if (msg.updateComponents) {
            for (const comp of msg.updateComponents.components) {
              if (comp.component === 'WeatherCard') {
                a2uiComponents = comp.props;
              }
            }
          }
        }
      }

      setMessages(prev => [...prev, {
        id: Date.now().toString() + 'b',
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



  const pickImage = async () => {
    let result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      base64: true,
      quality: 0.5,
    });

    if (!result.canceled) {
      setSelectedImage(result.assets[0]);
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

  const renderItem = useCallback(({ item }: { item: any }) => {
    return <MessageItem item={item} />;
  }, []);

  return (
    <LinearGradient colors={['#09090b', '#1e1b4b', '#09090b']} style={[styles.container, { paddingTop: insets.top }]}>
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior="padding"
        enabled={Platform.OS === 'ios' ? true : isKeyboardVisible}
        keyboardVerticalOffset={0}
      >
        {!isVoiceMode && (
          <View style={styles.header}>
            <TouchableOpacity onPress={() => navigation.dispatch(DrawerActions.openDrawer())}>
              <Feather name="menu" size={24} color="#fff" />
            </TouchableOpacity>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
              <MaterialIcons name="auto-awesome" size={20} color="#a855f7" />
              <Text style={styles.headerTitle}>Assistant</Text>
            </View>
            <TouchableOpacity onPress={openAccountModal}>
              <Feather name="user" size={24} color="#fff" />
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
                {fillerText ? fillerText : (isPlaying ? 'AI is speaking...' : isLoading ? 'Thinking...' : isRecording ? 'Listening...' : 'Speak freely...')}
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

              {isPlaying && (
                <TouchableOpacity style={styles.interruptBtn} onPress={handleInterrupt}>
                  <Feather name="mic-off" size={24} color="#fff" />
                  <Text style={styles.interruptText}>Interrupt</Text>
                </TouchableOpacity>
              )}
            </View>
          </View>
        ) : (
          <>
            <FlatList
              data={messages}
              keyExtractor={item => item.id}
              renderItem={renderItem}
              contentContainerStyle={[styles.listContent, { flexGrow: 1 }]}
              initialNumToRender={15}
              maxToRenderPerBatch={10}
              windowSize={10}
              removeClippedSubviews={Platform.OS === 'android'}
              ListEmptyComponent={
                <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center', padding: 20 }}>
                  <Text style={{ color: '#a1a1aa', fontSize: 18, fontWeight: '500', textAlign: 'center' }}>Hello! How can I help you today?</Text>
                </View>
              }
              ListFooterComponent={
                isLoading ? (
                  <View style={[styles.messageWrapper, styles.messageBot]}>
                    <View style={[
                      styles.messageBubble,
                      styles.bubbleBot,
                      { backgroundColor: 'transparent', borderWidth: 0 }
                    ]}>
                      <Text style={[styles.messageText, { color: '#a1a1aa', fontStyle: 'italic' }]}>
                        🧠 {loadingText}
                      </Text>
                    </View>
                  </View>
                ) : null
              }
            />


            <Animated.View style={[
              animatedBorderStyle,
              {
                marginBottom: isKeyboardVisible ? 12 : Math.max(insets.bottom, 12),
                marginHorizontal: 12,
                borderRadius: 34,
                padding: 2,
              }
            ]}>
              <View style={[styles.inputArea, { marginBottom: 0, marginHorizontal: 0 }]}>
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

                    {selectedImage && (
                      <View style={{ position: 'relative', marginHorizontal: 4 }}>
                        <Image source={{ uri: selectedImage.uri }} style={{ width: 36, height: 36, borderRadius: 8 }} />
                        <TouchableOpacity
                          style={{ position: 'absolute', top: -6, right: -6, backgroundColor: 'rgba(0,0,0,0.6)', borderRadius: 10, width: 20, height: 20, justifyContent: 'center', alignItems: 'center' }}
                          onPress={() => setSelectedImage(null)}
                        >
                          <Feather name="x" size={14} color="#fff" />
                        </TouchableOpacity>
                      </View>
                    )}

                    <TextInput
                      style={styles.input}
                      placeholder="Message..."
                      placeholderTextColor="#a1a1aa"
                      value={inputText}
                      onChangeText={setInputText}
                      onSubmitEditing={handleSendText}
                    />

                    {inputText.length === 0 && !selectedImage ? (
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
            </Animated.View>

            {isPlusMenuOpen && (
              <View style={styles.plusMenu}>
                <TouchableOpacity style={styles.menuItem} onPress={() => { setIsPlusMenuOpen(false); pickImage(); }}>
                  <Feather name="image" size={20} color="#a855f7" />
                  <Text style={styles.menuText}>Upload Photo</Text>
                </TouchableOpacity>
                <TouchableOpacity style={styles.menuItem} onPress={() => { setIsPlusMenuOpen(false); pickDocument(); }}>
                  <Feather name="file-text" size={20} color="#a855f7" />
                  <Text style={styles.menuText}>Upload Document</Text>
                </TouchableOpacity>
              </View>
            )}
          </>
        )}
      </KeyboardAvoidingView>

      <Modal visible={isAccountModalOpen} animationType="slide" transparent={true} onRequestClose={() => setIsAccountModalOpen(false)}>
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>Account Profile</Text>
              <TouchableOpacity onPress={() => setIsAccountModalOpen(false)}>
                <Feather name="x" size={24} color="#fff" />
              </TouchableOpacity>
            </View>

            <ScrollView style={styles.modalBody}>
              <Text style={styles.modalLabel}>User ID</Text>
              <Text style={styles.modalValue}>{userId || 'Loading...'}</Text>

              <Text style={styles.modalLabel}>Stored Memories</Text>
              {isLoadingMemories ? (
                <ActivityIndicator color="#a855f7" />
              ) : userMemories.length > 0 ? (
                userMemories.map((mem, i) => (
                  <View key={i} style={styles.memoryCard}>
                    <Text style={styles.memoryText}>• {mem}</Text>
                  </View>
                ))
              ) : (
                <Text style={styles.noMemoriesText}>No memories stored yet.</Text>
              )}
            </ScrollView>

            <TouchableOpacity style={styles.logoutBtn} onPress={() => {
              setIsAccountModalOpen(false);
              supabase.auth.signOut();
            }}>
              <Feather name="log-out" size={20} color="#fff" />
              <Text style={styles.logoutBtnText}>Logout</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
    </LinearGradient>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: 'transparent',
  },
  header: {
    paddingTop: 15,
    paddingBottom: 15,
    paddingHorizontal: 20,
    backgroundColor: 'rgba(24, 24, 27, 0.4)',
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(39, 39, 42, 0.3)',
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
    backgroundColor: 'transparent',
    maxWidth: '100%',
    paddingHorizontal: 0,
    paddingVertical: 4,
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
    backgroundColor: 'rgba(24, 24, 27, 0.95)',
    alignItems: 'center',
    borderRadius: 32,
    width: '100%',
  },
  input: {
    flex: 1,
    backgroundColor: '#27272a',
    color: '#fff',
    borderRadius: 24,
    paddingHorizontal: 20,
    paddingVertical: 14,
    fontSize: 18,
    marginHorizontal: 8,
    maxHeight: 120,
  },
  iconBtn: {
    padding: 10,
  },
  iconTxt: {
    fontSize: 24,
  },
  sendBtn: {
    backgroundColor: '#007bff',
    width: 44,
    height: 44,
    borderRadius: 22,
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
  interruptBtn: {
    alignSelf: 'center',
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#ef4444',
    paddingHorizontal: 20,
    paddingVertical: 12,
    borderRadius: 30,
    marginTop: 40,
    elevation: 5,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.3,
    shadowRadius: 3,
  },
  interruptText: {
    color: '#fff',
    fontWeight: 'bold',
    marginLeft: 8,
    fontSize: 16,
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
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.5)',
    justifyContent: 'flex-end',
  },
  modalContent: {
    backgroundColor: '#18181b',
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    padding: 24,
    maxHeight: '80%',
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 24,
  },
  modalTitle: {
    color: '#fff',
    fontSize: 20,
    fontWeight: 'bold',
  },
  modalBody: {
    marginBottom: 24,
  },
  modalLabel: {
    color: '#a1a1aa',
    fontSize: 14,
    marginBottom: 8,
    textTransform: 'uppercase',
    letterSpacing: 1,
  },
  modalValue: {
    color: '#fff',
    fontSize: 16,
    marginBottom: 24,
    backgroundColor: '#27272a',
    padding: 12,
    borderRadius: 12,
  },
  memoryCard: {
    backgroundColor: '#27272a',
    padding: 12,
    borderRadius: 12,
    marginBottom: 8,
  },
  memoryText: {
    color: '#fff',
    fontSize: 15,
    lineHeight: 22,
  },
  noMemoriesText: {
    color: '#a1a1aa',
    fontStyle: 'italic',
    marginBottom: 20,
  },
  logoutBtn: {
    backgroundColor: '#ef4444',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 16,
    borderRadius: 16,
    gap: 8,
  },
  logoutBtnText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: 'bold',
  },
});
