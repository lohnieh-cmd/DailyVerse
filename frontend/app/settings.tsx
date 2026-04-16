import React, { useEffect, useState, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  TextInput,
  Alert,
  ActivityIndicator,
  Switch,
  Modal,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { StatusBar } from 'expo-status-bar';
import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import * as DocumentPicker from 'expo-document-picker';
import * as FileSystem from 'expo-file-system';
import { Audio } from 'expo-av';

const BACKEND_URL = process.env.EXPO_PUBLIC_BACKEND_URL;

interface Verse {
  _id: string;
  reference: string;
  text: string;
  translation?: string;
  language?: string;
  audio_base64?: string;
  order: number;
  date_added: string;
}

interface Settings {
  notification_time: string;
  notification_enabled: boolean;
}

export default function SettingsScreen() {
  const [verses, setVerses] = useState<Verse[]>([]);
  const [settings, setSettings] = useState<Settings>({
    notification_time: '07:00',
    notification_enabled: true,
  });
  const [loading, setLoading] = useState(true);
  const [modalVisible, setModalVisible] = useState(false);
  const [editingVerse, setEditingVerse] = useState<Verse | null>(null);
  const [newReference, setNewReference] = useState('');
  const [newText, setNewText] = useState('');
  const [recording, setRecording] = useState<Audio.Recording | null>(null);
  const [recordedAudio, setRecordedAudio] = useState<string | null>(null);
  const [isRecording, setIsRecording] = useState(false);
  const [importing, setImporting] = useState(false);
  const [seeding, setSeeding] = useState(false);

  const fetchData = async () => {
    try {
      const [versesRes, settingsRes] = await Promise.all([
        fetch(`${BACKEND_URL}/api/verses`),
        fetch(`${BACKEND_URL}/api/settings`),
      ]);
      
      const versesData = await versesRes.json();
      const settingsData = await settingsRes.json();
      
      setVerses(versesData);
      setSettings(settingsData);
    } catch (err) {
      console.error('Error fetching data:', err);
      Alert.alert('Error', 'Failed to load data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleImportExcel = async () => {
    if (Platform.OS === 'web') {
      // For web, use native HTML file input
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = '.xlsx,.xls,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel';
      
      input.onchange = async (e: any) => {
        const file = e.target.files?.[0];
        if (!file) return;
        
        setImporting(true);
        try {
          const formData = new FormData();
          formData.append('file', file);
          
          const uploadResponse = await fetch(`${BACKEND_URL}/api/import/excel`, {
            method: 'POST',
            body: formData,
          });
          
          const data = await uploadResponse.json();
          
          if (uploadResponse.ok) {
            Alert.alert(
              'Import Complete',
              `Imported ${data.imported_count} verses.${data.failed_references?.length ? `\nFailed: ${data.failed_references.slice(0, 5).join(', ')}${data.failed_references.length > 5 ? '...' : ''}` : ''}`
            );
            fetchData();
          } else {
            Alert.alert('Import Failed', data.detail || 'Unknown error');
          }
        } catch (err) {
          console.error('Web upload error:', err);
          Alert.alert('Error', 'Failed to upload file');
        } finally {
          setImporting(false);
        }
      };
      
      input.click();
      return;
    }
    
    // For native mobile
    try {
      const result = await DocumentPicker.getDocumentAsync({
        type: [
          'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
          'application/vnd.ms-excel',
        ],
        copyToCacheDirectory: true,
      });

      if (result.canceled || !result.assets?.[0]) {
        return;
      }

      setImporting(true);
      const file = result.assets[0];
      
      const formData = new FormData();
      formData.append('file', {
        uri: file.uri,
        name: file.name,
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      } as any);

      const uploadResponse = await fetch(`${BACKEND_URL}/api/import/excel`, {
        method: 'POST',
        body: formData,
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });

      const data = await uploadResponse.json();
      
      if (uploadResponse.ok) {
        Alert.alert(
          'Import Complete',
          `Imported ${data.imported_count} verses.${data.failed_references?.length ? `\nFailed: ${data.failed_references.slice(0, 5).join(', ')}${data.failed_references.length > 5 ? '...' : ''}` : ''}`
        );
        fetchData();
      } else {
        Alert.alert('Import Failed', data.detail || 'Unknown error');
      }
    } catch (err) {
      console.error('Import error:', err);
      Alert.alert('Error', 'Failed to import file');
    } finally {
      setImporting(false);
    }
  };

  const handleSeedSampleVerses = async () => {
    try {
      setSeeding(true);
      const response = await fetch(`${BACKEND_URL}/api/seed`, {
        method: 'POST',
      });
      const data = await response.json();
      
      Alert.alert('Seed Complete', data.message);
      fetchData();
    } catch (err) {
      console.error('Seed error:', err);
      Alert.alert('Error', 'Failed to seed verses');
    } finally {
      setSeeding(false);
    }
  };

  const handleAddVerse = () => {
    setEditingVerse(null);
    setNewReference('');
    setNewText('');
    setRecordedAudio(null);
    setModalVisible(true);
  };

  const handleEditVerse = (verse: Verse) => {
    setEditingVerse(verse);
    setNewReference(verse.reference);
    setNewText(verse.text);
    setRecordedAudio(verse.audio_base64 || null);
    setModalVisible(true);
  };

  const handleDeleteVerse = (verse: Verse) => {
    Alert.alert(
      'Delete Verse',
      `Are you sure you want to delete "${verse.reference}"?`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Delete',
          style: 'destructive',
          onPress: async () => {
            try {
              await fetch(`${BACKEND_URL}/api/verses/${verse._id}`, {
                method: 'DELETE',
              });
              fetchData();
            } catch (err) {
              Alert.alert('Error', 'Failed to delete verse');
            }
          },
        },
      ]
    );
  };

  const handleSaveVerse = async () => {
    if (!newReference.trim()) {
      Alert.alert('Error', 'Please enter a verse reference');
      return;
    }

    try {
      const body = {
        reference: newReference.trim(),
        text: newText.trim() || undefined,
        audio_base64: recordedAudio || undefined,
      };

      if (editingVerse) {
        await fetch(`${BACKEND_URL}/api/verses/${editingVerse._id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
      } else {
        const response = await fetch(`${BACKEND_URL}/api/verses`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        
        if (!response.ok) {
          const error = await response.json();
          Alert.alert('Error', error.detail);
          return;
        }
      }

      setModalVisible(false);
      fetchData();
    } catch (err) {
      console.error('Save error:', err);
      Alert.alert('Error', 'Failed to save verse');
    }
  };

  const startRecording = async () => {
    try {
      await Audio.requestPermissionsAsync();
      await Audio.setAudioModeAsync({
        allowsRecordingIOS: true,
        playsInSilentModeIOS: true,
      });

      const { recording } = await Audio.Recording.createAsync(
        Audio.RecordingOptionsPresets.HIGH_QUALITY
      );
      
      setRecording(recording);
      setIsRecording(true);
    } catch (err) {
      console.error('Recording error:', err);
      Alert.alert('Error', 'Failed to start recording');
    }
  };

  const stopRecording = async () => {
    if (!recording) return;

    try {
      await recording.stopAndUnloadAsync();
      const uri = recording.getURI();
      
      if (uri) {
        const base64 = await FileSystem.readAsStringAsync(uri, {
          encoding: 'base64',
        });
        setRecordedAudio(base64);
      }
      
      setRecording(null);
      setIsRecording(false);
    } catch (err) {
      console.error('Stop recording error:', err);
      Alert.alert('Error', 'Failed to stop recording');
    }
  };

  const importAudioFile = async () => {
    try {
      const result = await DocumentPicker.getDocumentAsync({
        type: ['audio/*'],
        copyToCacheDirectory: true,
      });

      if (result.canceled || !result.assets?.[0]) {
        return;
      }

      const file = result.assets[0];
      console.log('Selected audio file:', file);

      // Check file size (limit to 10MB for base64 encoding)
      if (file.size && file.size > 10 * 1024 * 1024) {
        Alert.alert('File Too Large', 'Please select an audio file smaller than 10MB');
        return;
      }

      // Read file and convert to base64
      let base64: string;
      
      if (Platform.OS === 'web') {
        // For web, fetch the file and convert to base64
        const response = await fetch(file.uri);
        const blob = await response.blob();
        base64 = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onloadend = () => {
            const result = reader.result as string;
            // Remove data URL prefix (e.g., "data:audio/mp4;base64,")
            const base64Data = result.split(',')[1];
            resolve(base64Data);
          };
          reader.onerror = reject;
          reader.readAsDataURL(blob);
        });
      } else {
        // For native, use FileSystem
        base64 = await FileSystem.readAsStringAsync(file.uri, {
          encoding: 'base64',
        });
      }

      setRecordedAudio(base64);
      Alert.alert('Success', `Audio file "${file.name}" imported successfully!`);
    } catch (err) {
      console.error('Import audio error:', err);
      Alert.alert('Error', 'Failed to import audio file');
    }
  };

  const handleNotificationToggle = async (enabled: boolean) => {
    try {
      setSettings(prev => ({ ...prev, notification_enabled: enabled }));
      await fetch(`${BACKEND_URL}/api/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ notification_enabled: enabled }),
      });
    } catch (err) {
      console.error('Settings update error:', err);
    }
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.container} edges={['top']}>
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color="#D4AF37" />
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <StatusBar style="light" />
      
      <View style={styles.header}>
        <TouchableOpacity 
          style={styles.backButton}
          onPress={() => router.back()}
        >
          <Ionicons name="arrow-back" size={24} color="#FFF" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Settings</Text>
        <View style={styles.headerSpacer} />
      </View>

      <ScrollView style={styles.content}>
        {/* Notifications Section */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Notifications</Text>
          <View style={styles.settingRow}>
            <View style={styles.settingInfo}>
              <Ionicons name="notifications-outline" size={24} color="#D4AF37" />
              <Text style={styles.settingLabel}>Daily Reminder</Text>
            </View>
            <Switch
              value={settings.notification_enabled}
              onValueChange={handleNotificationToggle}
              trackColor={{ false: '#333', true: '#D4AF37' }}
              thumbColor="#FFF"
            />
          </View>
          <Text style={styles.settingDescription}>
            Receive a notification at {settings.notification_time} on working days
          </Text>
        </View>

        {/* Import Section */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Import Verses</Text>
          
          <TouchableOpacity 
            style={styles.importButton}
            onPress={handleImportExcel}
            disabled={importing}
          >
            {importing ? (
              <ActivityIndicator color="#1A1A2E" />
            ) : (
              <>
                <Ionicons name="document-outline" size={24} color="#1A1A2E" />
                <Text style={styles.importButtonText}>Import from Excel</Text>
              </>
            )}
          </TouchableOpacity>
          <Text style={styles.importHint}>
            Required columns:{"\n"}
            • Column A: Verse reference (e.g., "Matt 21:22"){"\n"}
            • Column B: Translation (e.g., "NLV", "AFR53", "NIV"){"\n"}
            • Column C: Language (e.g., "Afr", "Eng"){"\n"}
            • Column D: Bible.com URL{"\n\n"}
            URL format: https://www.bible.com/bible/ID/BOOK.CH.VS.TRANS{"\n"}
            Examples:{"\n"}
            • NLV: bible.com/bible/117/MAT.21.22.NLV{"\n"}
            • AFR53: bible.com/bible/5/ISA.53.5.AFR53{"\n"}
            • NIV: bible.com/bible/111/JHN.3.16.NIV
          </Text>

          <TouchableOpacity 
            style={[styles.importButton, styles.seedButton]}
            onPress={handleSeedSampleVerses}
            disabled={seeding}
          >
            {seeding ? (
              <ActivityIndicator color="#D4AF37" />
            ) : (
              <>
                <Ionicons name="sparkles-outline" size={24} color="#D4AF37" />
                <Text style={[styles.importButtonText, styles.seedButtonText]}>
                  Seed Sample Verses
                </Text>
              </>
            )}
          </TouchableOpacity>
        </View>

        {/* Verses List Section */}
        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle}>Verses ({verses.length})</Text>
            <TouchableOpacity 
              style={styles.addButton}
              onPress={handleAddVerse}
            >
              <Ionicons name="add" size={24} color="#D4AF37" />
            </TouchableOpacity>
          </View>

          {verses.length === 0 ? (
            <Text style={styles.emptyText}>
              No verses yet. Import from Excel or add manually.
            </Text>
          ) : (
            verses.map((verse, index) => (
              <View key={verse._id} style={styles.verseItem}>
                <View style={styles.verseInfo}>
                  <Text style={styles.verseOrder}>#{verse.order}</Text>
                  <View style={styles.verseDetails}>
                    <View style={styles.verseHeader}>
                      <Text style={styles.verseReference}>{verse.reference}</Text>
                      {verse.translation && (
                        <Text style={styles.verseTranslation}>{verse.translation}</Text>
                      )}
                    </View>
                    {verse.language && (
                      <Text style={styles.verseLanguage}>
                        {verse.language === 'Afr' ? 'Afrikaans' : verse.language === 'Eng' ? 'English' : verse.language}
                      </Text>
                    )}
                    <Text style={styles.versePreview} numberOfLines={2}>
                      {verse.text}
                    </Text>
                    {verse.audio_base64 && (
                      <View style={styles.audioIndicator}>
                        <Ionicons name="mic" size={14} color="#D4AF37" />
                        <Text style={styles.audioIndicatorText}>Audio</Text>
                      </View>
                    )}
                  </View>
                </View>
                <View style={styles.verseActions}>
                  <TouchableOpacity
                    style={styles.actionButton}
                    onPress={() => handleEditVerse(verse)}
                  >
                    <Ionicons name="pencil" size={18} color="#888" />
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={styles.actionButton}
                    onPress={() => handleDeleteVerse(verse)}
                  >
                    <Ionicons name="trash-outline" size={18} color="#E74C3C" />
                  </TouchableOpacity>
                </View>
              </View>
            ))
          )}
        </View>
      </ScrollView>

      {/* Add/Edit Verse Modal */}
      <Modal
        visible={modalVisible}
        animationType="slide"
        transparent={true}
        onRequestClose={() => setModalVisible(false)}
      >
        <KeyboardAvoidingView 
          behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
          style={styles.modalOverlay}
        >
          <View style={styles.modalContent}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>
                {editingVerse ? 'Edit Verse' : 'Add New Verse'}
              </Text>
              <TouchableOpacity
                onPress={() => setModalVisible(false)}
              >
                <Ionicons name="close" size={24} color="#888" />
              </TouchableOpacity>
            </View>

            <ScrollView style={styles.modalBody}>
              <Text style={styles.inputLabel}>Reference *</Text>
              <TextInput
                style={styles.input}
                value={newReference}
                onChangeText={setNewReference}
                placeholder="e.g., John 3:16 or Psalm 23:1-3"
                placeholderTextColor="#666"
              />

              <Text style={styles.inputLabel}>Text (optional - auto-fetched if empty)</Text>
              <TextInput
                style={[styles.input, styles.textArea]}
                value={newText}
                onChangeText={setNewText}
                placeholder="Leave empty to auto-fetch from Bible API"
                placeholderTextColor="#666"
                multiline
                numberOfLines={4}
              />

              <Text style={styles.inputLabel}>Audio Recording (optional)</Text>
              <View style={styles.recordingContainer}>
                {recordedAudio ? (
                  <View style={styles.recordedIndicator}>
                    <Ionicons name="checkmark-circle" size={24} color="#27AE60" />
                    <Text style={styles.recordedText}>Audio attached</Text>
                    <TouchableOpacity onPress={() => setRecordedAudio(null)}>
                      <Ionicons name="close-circle" size={24} color="#E74C3C" />
                    </TouchableOpacity>
                  </View>
                ) : (
                  <View style={styles.audioOptionsContainer}>
                    <TouchableOpacity
                      style={[styles.audioOptionButton, isRecording && styles.recordingActive]}
                      onPress={isRecording ? stopRecording : startRecording}
                    >
                      <Ionicons 
                        name={isRecording ? "stop" : "mic"} 
                        size={28} 
                        color={isRecording ? "#E74C3C" : "#D4AF37"} 
                      />
                      <Text style={styles.audioOptionText}>
                        {isRecording ? 'Stop' : 'Record'}
                      </Text>
                    </TouchableOpacity>
                    
                    <View style={styles.audioOptionDivider} />
                    
                    <TouchableOpacity
                      style={styles.audioOptionButton}
                      onPress={importAudioFile}
                    >
                      <Ionicons name="folder-open" size={28} color="#D4AF37" />
                      <Text style={styles.audioOptionText}>Import</Text>
                    </TouchableOpacity>
                  </View>
                )}
              </View>
              <Text style={styles.audioHint}>
                Import voice memos from Files app or record directly
              </Text>
            </ScrollView>

            <View style={styles.modalFooter}>
              <TouchableOpacity
                style={styles.cancelButton}
                onPress={() => setModalVisible(false)}
              >
                <Text style={styles.cancelButtonText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={styles.saveButton}
                onPress={handleSaveVerse}
              >
                <Text style={styles.saveButtonText}>Save Verse</Text>
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#1A1A2E',
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 16,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(212, 175, 55, 0.2)',
  },
  backButton: {
    padding: 8,
  },
  headerTitle: {
    flex: 1,
    fontSize: 20,
    fontWeight: '700',
    color: '#FFF',
    textAlign: 'center',
  },
  headerSpacer: {
    width: 40,
  },
  content: {
    flex: 1,
  },
  section: {
    padding: 20,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255, 255, 255, 0.1)',
  },
  sectionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#D4AF37',
    marginBottom: 16,
  },
  settingRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    backgroundColor: 'rgba(255, 255, 255, 0.05)',
    padding: 16,
    borderRadius: 12,
  },
  settingInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  settingLabel: {
    fontSize: 16,
    color: '#FFF',
  },
  settingDescription: {
    marginTop: 8,
    fontSize: 13,
    color: '#888',
  },
  importButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 10,
    backgroundColor: '#D4AF37',
    padding: 16,
    borderRadius: 12,
    marginBottom: 12,
  },
  importButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1A1A2E',
  },
  seedButton: {
    backgroundColor: 'transparent',
    borderWidth: 1,
    borderColor: '#D4AF37',
  },
  seedButtonText: {
    color: '#D4AF37',
  },
  importHint: {
    fontSize: 13,
    color: '#888',
    marginBottom: 16,
    lineHeight: 20,
  },
  addButton: {
    padding: 8,
  },
  emptyText: {
    fontSize: 14,
    color: '#888',
    textAlign: 'center',
    paddingVertical: 20,
  },
  verseItem: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    backgroundColor: 'rgba(255, 255, 255, 0.05)',
    padding: 16,
    borderRadius: 12,
    marginBottom: 12,
  },
  verseInfo: {
    flex: 1,
    flexDirection: 'row',
    gap: 12,
  },
  verseOrder: {
    fontSize: 14,
    fontWeight: '600',
    color: '#D4AF37',
    minWidth: 30,
  },
  verseDetails: {
    flex: 1,
  },
  verseHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 2,
  },
  verseReference: {
    fontSize: 16,
    fontWeight: '600',
    color: '#FFF',
  },
  verseTranslation: {
    fontSize: 12,
    color: '#D4AF37',
    backgroundColor: 'rgba(212, 175, 55, 0.2)',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  verseLanguage: {
    fontSize: 11,
    color: '#888',
    marginBottom: 4,
  },
  versePreview: {
    fontSize: 13,
    color: '#888',
    lineHeight: 18,
  },
  audioIndicator: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    marginTop: 8,
  },
  audioIndicatorText: {
    fontSize: 12,
    color: '#D4AF37',
  },
  verseActions: {
    flexDirection: 'row',
    gap: 8,
  },
  actionButton: {
    padding: 8,
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.7)',
    justifyContent: 'flex-end',
  },
  modalContent: {
    backgroundColor: '#1A1A2E',
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    maxHeight: '90%',
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 20,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255, 255, 255, 0.1)',
  },
  modalTitle: {
    fontSize: 20,
    fontWeight: '700',
    color: '#FFF',
  },
  modalBody: {
    padding: 20,
  },
  inputLabel: {
    fontSize: 14,
    fontWeight: '600',
    color: '#D4AF37',
    marginBottom: 8,
  },
  input: {
    backgroundColor: 'rgba(255, 255, 255, 0.1)',
    borderRadius: 12,
    padding: 16,
    fontSize: 16,
    color: '#FFF',
    marginBottom: 20,
  },
  textArea: {
    minHeight: 100,
    textAlignVertical: 'top',
  },
  recordingContainer: {
    marginBottom: 8,
  },
  audioOptionsContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(255, 255, 255, 0.1)',
    borderRadius: 12,
    borderWidth: 2,
    borderColor: '#D4AF37',
    borderStyle: 'dashed',
    padding: 16,
  },
  audioOptionButton: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 12,
  },
  audioOptionText: {
    marginTop: 8,
    fontSize: 14,
    color: '#D4AF37',
  },
  audioOptionDivider: {
    width: 1,
    height: 50,
    backgroundColor: 'rgba(212, 175, 55, 0.3)',
    marginHorizontal: 16,
  },
  audioHint: {
    fontSize: 12,
    color: '#888',
    textAlign: 'center',
    marginBottom: 20,
  },
  recordButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 12,
    backgroundColor: 'rgba(255, 255, 255, 0.1)',
    padding: 20,
    borderRadius: 12,
    borderWidth: 2,
    borderColor: '#D4AF37',
    borderStyle: 'dashed',
  },
  recordingActive: {
    backgroundColor: 'rgba(231, 76, 60, 0.2)',
    borderColor: '#E74C3C',
  },
  recordButtonText: {
    fontSize: 16,
    color: '#FFF',
  },
  recordedIndicator: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    backgroundColor: 'rgba(39, 174, 96, 0.2)',
    padding: 16,
    borderRadius: 12,
  },
  recordedText: {
    flex: 1,
    fontSize: 16,
    color: '#27AE60',
  },
  modalFooter: {
    flexDirection: 'row',
    gap: 12,
    padding: 20,
    borderTopWidth: 1,
    borderTopColor: 'rgba(255, 255, 255, 0.1)',
  },
  cancelButton: {
    flex: 1,
    padding: 16,
    borderRadius: 12,
    backgroundColor: 'rgba(255, 255, 255, 0.1)',
    alignItems: 'center',
  },
  cancelButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#888',
  },
  saveButton: {
    flex: 1,
    padding: 16,
    borderRadius: 12,
    backgroundColor: '#D4AF37',
    alignItems: 'center',
  },
  saveButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1A1A2E',
  },
});
