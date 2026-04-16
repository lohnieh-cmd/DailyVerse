import React, { useEffect, useState, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  ActivityIndicator,
  RefreshControl,
  Platform,
  Share,
  Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { StatusBar } from 'expo-status-bar';
import { Ionicons } from '@expo/vector-icons';
import { Audio } from 'expo-av';
import { router } from 'expo-router';
import * as Notifications from 'expo-notifications';

const BACKEND_URL = process.env.EXPO_PUBLIC_BACKEND_URL;

interface TodayVerse {
  id?: string;
  reference?: string;
  text?: string;
  translation?: string;
  language?: string;
  audio_base64?: string;
  verse_number?: number;
  total_verses?: number;
  working_day_of_year?: number;
  date: string;
  is_weekend: boolean;
  is_holiday: boolean;
  holiday_name?: string;
  message?: string;
}

export default function HomeScreen() {
  const [verse, setVerse] = useState<TodayVerse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [sound, setSound] = useState<Audio.Sound | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchTodayVerse = async () => {
    try {
      setError(null);
      const response = await fetch(`${BACKEND_URL}/api/verse/today`);
      const data = await response.json();
      setVerse(data);
    } catch (err) {
      console.error('Error fetching verse:', err);
      setError('Unable to load today\'s verse. Please check your connection.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchTodayVerse();
    setupNotifications();
    
    return () => {
      if (sound) {
        sound.unloadAsync();
      }
    };
  }, []);

  const setupNotifications = async () => {
    const { status } = await Notifications.requestPermissionsAsync();
    if (status !== 'granted') {
      console.log('Notification permissions not granted');
    }
  };

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    fetchTodayVerse();
  }, []);

  const playAudio = async () => {
    if (!verse?.audio_base64) return;

    try {
      if (sound) {
        if (isPlaying) {
          await sound.pauseAsync();
          setIsPlaying(false);
        } else {
          await sound.playAsync();
          setIsPlaying(true);
        }
      } else {
        const { sound: newSound } = await Audio.Sound.createAsync(
          { uri: `data:audio/mp3;base64,${verse.audio_base64}` },
          { shouldPlay: true }
        );
        setSound(newSound);
        setIsPlaying(true);
        
        newSound.setOnPlaybackStatusUpdate((status) => {
          if (status.isLoaded && status.didJustFinish) {
            setIsPlaying(false);
          }
        });
      }
    } catch (err) {
      console.error('Error playing audio:', err);
    }
  };

  const shareVerse = async () => {
    if (!verse?.reference || !verse?.text) return;

    try {
      const translationInfo = verse.translation ? ` (${verse.translation})` : '';
      const message = `📖 ${verse.reference}${translationInfo}\n\n"${verse.text}"\n\n— Daily Scripture Verse`;
      
      const result = await Share.share({
        message: message,
        title: `${verse.reference} - Daily Scripture`,
      });

      if (result.action === Share.sharedAction) {
        if (result.activityType) {
          console.log('Shared with activity type:', result.activityType);
        } else {
          console.log('Verse shared successfully');
        }
      }
    } catch (error: any) {
      Alert.alert('Error', 'Could not share the verse');
      console.error('Share error:', error);
    }
  };

  const renderContent = () => {
    if (loading) {
      return (
        <View style={styles.centerContent}>
          <ActivityIndicator size="large" color="#D4AF37" />
          <Text style={styles.loadingText}>Loading today's verse...</Text>
        </View>
      );
    }

    if (error) {
      return (
        <View style={styles.centerContent}>
          <Ionicons name="cloud-offline-outline" size={64} color="#666" />
          <Text style={styles.errorText}>{error}</Text>
          <TouchableOpacity style={styles.retryButton} onPress={fetchTodayVerse}>
            <Text style={styles.retryButtonText}>Retry</Text>
          </TouchableOpacity>
        </View>
      );
    }

    if (verse?.is_weekend) {
      return (
        <View style={styles.centerContent}>
          <Ionicons name="sunny-outline" size={80} color="#D4AF37" />
          <Text style={styles.restDayTitle}>Rest Day</Text>
          <Text style={styles.restDaySubtitle}>It's the weekend!</Text>
          <Text style={styles.restDayMessage}>
            Take time to rest and reflect. See you on Monday!
          </Text>
        </View>
      );
    }

    if (verse?.is_holiday) {
      return (
        <View style={styles.centerContent}>
          <Ionicons name="calendar-outline" size={80} color="#D4AF37" />
          <Text style={styles.restDayTitle}>Public Holiday</Text>
          <Text style={styles.restDaySubtitle}>{verse.holiday_name}</Text>
          <Text style={styles.restDayMessage}>
            Enjoy your holiday! Regular verses resume tomorrow.
          </Text>
        </View>
      );
    }

    if (verse?.message && !verse.reference) {
      return (
        <View style={styles.centerContent}>
          <Ionicons name="book-outline" size={64} color="#666" />
          <Text style={styles.noVerseText}>{verse.message}</Text>
          <TouchableOpacity 
            style={styles.addVerseButton}
            onPress={() => router.push('/settings')}
          >
            <Ionicons name="add-circle-outline" size={20} color="#FFF" />
            <Text style={styles.addVerseButtonText}>Add Verses</Text>
          </TouchableOpacity>
        </View>
      );
    }

    return (
      <View style={styles.verseContainer}>
        <View style={styles.dateContainer}>
          <Text style={styles.dateText}>
            {new Date(verse?.date || '').toLocaleDateString('en-ZA', {
              weekday: 'long',
              year: 'numeric',
              month: 'long',
              day: 'numeric',
            })}
          </Text>
        </View>

        <View style={styles.referenceContainer}>
          <Ionicons name="book" size={24} color="#D4AF37" />
          <View style={styles.referenceInfo}>
            <Text style={styles.referenceText}>{verse?.reference}</Text>
            {verse?.translation && (
              <Text style={styles.translationText}>
                {verse.translation} • {verse.language === 'Afr' ? 'Afrikaans' : verse.language === 'Eng' ? 'English' : verse.language}
              </Text>
            )}
          </View>
        </View>

        <ScrollView 
          style={styles.textScrollView}
          showsVerticalScrollIndicator={false}
        >
          <Text style={styles.verseText}>"{verse?.text}"</Text>
        </ScrollView>

        <View style={styles.actionButtonsContainer}>
          {verse?.audio_base64 && (
            <TouchableOpacity style={styles.actionButton} onPress={playAudio}>
              <Ionicons 
                name={isPlaying ? "pause-circle" : "play-circle"} 
                size={48} 
                color="#D4AF37" 
              />
              <Text style={styles.actionButtonText}>
                {isPlaying ? 'Pause' : 'Listen'}
              </Text>
            </TouchableOpacity>
          )}
          
          <TouchableOpacity style={styles.actionButton} onPress={shareVerse}>
            <Ionicons name="share-social" size={48} color="#D4AF37" />
            <Text style={styles.actionButtonText}>Share</Text>
          </TouchableOpacity>
        </View>

        <View style={styles.progressContainer}>
          <Text style={styles.progressText}>
            Verse {verse?.verse_number} of {verse?.total_verses}
          </Text>
          <Text style={styles.workingDayText}>
            Working day {verse?.working_day_of_year} of the year
          </Text>
        </View>
      </View>
    );
  };

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <StatusBar style="light" />
      
      <View style={styles.header}>
        <Text style={styles.headerTitle}>Daily Scripture</Text>
        <TouchableOpacity 
          style={styles.settingsButton}
          onPress={() => router.push('/settings')}
        >
          <Ionicons name="settings-outline" size={24} color="#FFF" />
        </TouchableOpacity>
      </View>

      <ScrollView
        contentContainerStyle={styles.scrollContent}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor="#D4AF37"
            colors={['#D4AF37']}
          />
        }
      >
        {renderContent()}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#1A1A2E',
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingVertical: 16,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(212, 175, 55, 0.2)',
  },
  headerTitle: {
    fontSize: 24,
    fontWeight: '700',
    color: '#D4AF37',
    letterSpacing: 0.5,
  },
  settingsButton: {
    padding: 8,
  },
  scrollContent: {
    flexGrow: 1,
    padding: 20,
  },
  centerContent: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingVertical: 60,
  },
  loadingText: {
    marginTop: 16,
    fontSize: 16,
    color: '#888',
  },
  errorText: {
    marginTop: 16,
    fontSize: 16,
    color: '#888',
    textAlign: 'center',
    paddingHorizontal: 20,
  },
  retryButton: {
    marginTop: 20,
    backgroundColor: '#D4AF37',
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderRadius: 8,
  },
  retryButtonText: {
    color: '#1A1A2E',
    fontSize: 16,
    fontWeight: '600',
  },
  restDayTitle: {
    marginTop: 24,
    fontSize: 28,
    fontWeight: '700',
    color: '#FFF',
  },
  restDaySubtitle: {
    marginTop: 8,
    fontSize: 18,
    color: '#D4AF37',
  },
  restDayMessage: {
    marginTop: 16,
    fontSize: 16,
    color: '#888',
    textAlign: 'center',
    paddingHorizontal: 40,
  },
  noVerseText: {
    marginTop: 16,
    fontSize: 16,
    color: '#888',
    textAlign: 'center',
  },
  addVerseButton: {
    marginTop: 20,
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#D4AF37',
    paddingHorizontal: 20,
    paddingVertical: 12,
    borderRadius: 8,
    gap: 8,
  },
  addVerseButtonText: {
    color: '#1A1A2E',
    fontSize: 16,
    fontWeight: '600',
  },
  verseContainer: {
    flex: 1,
  },
  dateContainer: {
    alignItems: 'center',
    marginBottom: 24,
  },
  dateText: {
    fontSize: 14,
    color: '#888',
    letterSpacing: 0.5,
  },
  referenceContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 10,
    marginBottom: 24,
    paddingVertical: 12,
    paddingHorizontal: 16,
    backgroundColor: 'rgba(212, 175, 55, 0.1)',
    borderRadius: 12,
  },
  referenceInfo: {
    alignItems: 'center',
  },
  referenceText: {
    fontSize: 20,
    fontWeight: '600',
    color: '#D4AF37',
  },
  translationText: {
    fontSize: 12,
    color: '#888',
    marginTop: 4,
  },
  textScrollView: {
    maxHeight: 300,
    marginBottom: 24,
  },
  verseText: {
    fontSize: 22,
    lineHeight: 34,
    color: '#F5F5F5',
    textAlign: 'center',
    fontStyle: 'italic',
  },
  actionButtonsContainer: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    gap: 40,
    marginVertical: 20,
  },
  actionButton: {
    alignItems: 'center',
  },
  actionButtonText: {
    marginTop: 8,
    fontSize: 14,
    color: '#D4AF37',
  },
  audioButton: {
    alignItems: 'center',
    marginVertical: 20,
  },
  audioButtonText: {
    marginTop: 8,
    fontSize: 14,
    color: '#D4AF37',
  },
  progressContainer: {
    alignItems: 'center',
    paddingTop: 20,
    borderTopWidth: 1,
    borderTopColor: 'rgba(255, 255, 255, 0.1)',
  },
  progressText: {
    fontSize: 14,
    color: '#888',
  },
  workingDayText: {
    fontSize: 12,
    color: '#666',
    marginTop: 4,
  },
});
