import { Drawer } from 'expo-router/drawer';
import { View, Text, TouchableOpacity, StyleSheet, FlatList, Modal, ActivityIndicator, ScrollView } from 'react-native';
import { useEffect, useState } from 'react';
import { fetchSessions } from '../../services/api';
import { Feather } from '@expo/vector-icons';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { useDrawerStatus } from '@react-navigation/drawer';
import { supabase } from '../../utils/supabaseClient';

function CustomDrawerContent(props: any) {
  const [sessions, setSessions] = useState<any[]>([]);
  const [showAllSessions, setShowAllSessions] = useState(false);
  const [settingsVisible, setSettingsVisible] = useState(false);
  const [userId, setUserId] = useState<string | null>(null);


  const router = useRouter();
  const params = useLocalSearchParams();
  const activeSessionId = params.sessionId as string;
  const isDrawerOpen = useDrawerStatus() === 'open';

  const handleOpenSettings = async () => {
    setSettingsVisible(true);
    try {
      const { data: { session } } = await supabase.auth.getSession();
      setUserId(session?.user?.email || 'N/A');
    } catch (err) {
      console.error(err);
    }
  };

  // Fetch when drawer opens
  useEffect(() => {
    if (isDrawerOpen) {
      loadSessions();
    }
  }, [isDrawerOpen]);

  // Fetch when a new session is created or changed
  useEffect(() => {
    loadSessions();
  }, [activeSessionId]);

  const loadSessions = async () => {
    try {
      const data = await fetchSessions();
      setSessions(data);
    } catch (e) {
      console.error(e);
    }
  };

  const handleSessionPress = (sessionId: string) => {
    router.push({ pathname: '/chat', params: { sessionId } });
    props.navigation.closeDrawer();
  };

  const handleNewChat = () => {
    // Pass a unique timestamp to forcefully break Expo's route caching
    // and guarantee the chat screen's useEffect triggers a full reset.
    router.push({ pathname: '/chat', params: { newChat: Date.now().toString() } });
    props.navigation.closeDrawer();
  };

  return (
    <View style={styles.drawerContainer}>
      <View style={styles.drawerHeader}>
        <Text style={styles.drawerTitle}>Chat History</Text>
      </View>
      
      <TouchableOpacity style={styles.newChatBtn} onPress={handleNewChat}>
        <Feather name="plus" size={20} color="#fff" />
        <Text style={styles.newChatText}>New Chat</Text>
      </TouchableOpacity>


      <FlatList
        data={showAllSessions ? sessions : sessions.slice(0, 5)}
        keyExtractor={(item, index) => item.session_id ? item.session_id.toString() : index.toString()}
        contentContainerStyle={{ padding: 12 }}
        renderItem={({ item }) => (
          <TouchableOpacity 
            style={[styles.sessionItem, activeSessionId === item.session_id && styles.activeSessionItem]}
            onPress={() => handleSessionPress(item.session_id)}
          >
            <Feather name="message-square" size={18} color={activeSessionId === item.session_id ? "#a855f7" : "#a1a1aa"} />
            <Text style={[styles.sessionText, activeSessionId === item.session_id && styles.activeSessionText]} numberOfLines={1}>
              {item.title || 'New Conversation'}
            </Text>
          </TouchableOpacity>
        )}
        ListFooterComponent={() => (
          <>
            {sessions.length > 5 && (
              <TouchableOpacity onPress={() => setShowAllSessions(!showAllSessions)} style={{ padding: 12, alignItems: 'center' }}>
                <Text style={{ color: '#a1a1aa', fontSize: 14 }}>{showAllSessions ? 'Show Less' : 'Load More'}</Text>
              </TouchableOpacity>
            )}
          </>
        )}
      />

    </View>
  );
}

export default function AppLayout() {
  return (
    <Drawer 
      screenOptions={{ 
        headerShown: false,
        drawerStyle: { width: '80%' }
      }}
      drawerContent={(props) => <CustomDrawerContent {...props} />}
    >
      <Drawer.Screen name="chat" />
    </Drawer>
  );
}

const styles = StyleSheet.create({
  drawerContainer: {
    flex: 1,
    backgroundColor: '#09090b',
  },
  drawerHeader: {
    paddingTop: 60,
    paddingBottom: 20,
    paddingHorizontal: 20,
    borderBottomWidth: 1,
    borderBottomColor: '#27272a',
  },
  drawerTitle: {
    color: '#fff',
    fontSize: 20,
    fontWeight: 'bold',
  },
  newChatBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#007bff',
    margin: 12,
    padding: 12,
    borderRadius: 8,
    justifyContent: 'center',
  },
  newChatText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
    marginLeft: 8,
  },
  sessionItem: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 12,
    borderRadius: 8,
    marginBottom: 4,
  },
  activeSessionItem: {
    backgroundColor: '#18181b',
  },
  sessionText: {
    color: '#a1a1aa',
    fontSize: 16,
    marginLeft: 12,
    flex: 1,
  },
  activeSessionText: {
    color: '#e4e4e7',
    fontWeight: '500',
  },
  settingsBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 16,
    paddingBottom: 48,
    borderTopWidth: 1,
    borderTopColor: '#27272a',
  },
  settingsText: {
    color: '#a1a1aa',
    fontSize: 16,
    marginLeft: 12,
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.6)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  modalContent: {
    width: '90%',
    maxHeight: '80%',
    backgroundColor: '#18181b',
    borderRadius: 12,
    padding: 20,
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 20,
  },
  modalTitle: {
    color: '#fff',
    fontSize: 20,
    fontWeight: 'bold',
  },
  modalLabel: {
    color: '#a1a1aa',
    fontSize: 14,
    marginBottom: 8,
    fontWeight: 'bold',
  },
  modalBox: {
    backgroundColor: '#27272a',
    padding: 12,
    borderRadius: 8,
    marginBottom: 16,
  },
  modalText: {
    color: '#e4e4e7',
    fontSize: 14,
  },
});
