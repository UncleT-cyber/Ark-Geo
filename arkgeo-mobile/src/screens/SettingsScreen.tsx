/**
 * SettingsScreen — emergency contact & threshold setup.
 */
import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TextInput,
  TouchableOpacity,
  ScrollView,
  Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import * as SecureStore from 'expo-secure-store';
import { Colors, Typography, Spacing, BorderRadius } from '../theme';

interface Contact {
  name: string;
  phone: string;
}

export function SettingsScreen() {
  const [contacts, setContacts] = useState<Contact[]>([
    { name: 'Emergency Contact', phone: '+15551234567' },
  ]);
  const [apiUrl, setApiUrl] = useState('');
  const [zeroRetention, setZeroRetention] = useState(false);

  useEffect(() => {
    loadSettings();
  }, []);

  const loadSettings = async () => {
    try {
      const savedContacts = await SecureStore.getItemAsync('emergency_contacts');
      if (savedContacts) setContacts(JSON.parse(savedContacts));
      const savedUrl = await SecureStore.getItemAsync('api_url');
      if (savedUrl) setApiUrl(savedUrl);
      const zr = await SecureStore.getItemAsync('zero_retention');
      if (zr === 'true') setZeroRetention(true);
    } catch {
      // ignore
    }
  };

  const saveSettings = async () => {
    try {
      await SecureStore.setItemAsync('emergency_contacts', JSON.stringify(contacts));
      await SecureStore.setItemAsync('api_url', apiUrl);
      await SecureStore.setItemAsync('zero_retention', String(zeroRetention));
      Alert.alert('Saved', 'Settings saved securely.');
    } catch (err) {
      Alert.alert('Error', 'Could not save settings.');
    }
  };

  const addContact = () => {
    setContacts([...contacts, { name: '', phone: '' }]);
  };

  const updateContact = (index: number, field: keyof Contact, value: string) => {
    const updated = [...contacts];
    updated[index] = { ...updated[index], [field]: value };
    setContacts(updated);
  };

  const removeContact = (index: number) => {
    setContacts(contacts.filter((_, i) => i !== index));
  };

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.scroll}>
        <Text style={styles.title}>SETTINGS</Text>

        {/* Emergency Contacts */}
        <Text style={styles.sectionLabel}>EMERGENCY CONTACTS</Text>
        {contacts.map((contact, i) => (
          <View key={i} style={styles.contactRow}>
            <TextInput
              style={styles.input}
              placeholder="Name"
              placeholderTextColor={Colors.textMuted}
              value={contact.name}
              onChangeText={(v) => updateContact(i, 'name', v)}
            />
            <TextInput
              style={styles.input}
              placeholder="Phone (+country code)"
              placeholderTextColor={Colors.textMuted}
              value={contact.phone}
              onChangeText={(v) => updateContact(i, 'phone', v)}
              keyboardType="phone-pad"
            />
            {contacts.length > 1 && (
              <TouchableOpacity onPress={() => removeContact(i)}>
                <Text style={styles.removeText}>REMOVE</Text>
              </TouchableOpacity>
            )}
          </View>
        ))}
        <TouchableOpacity style={styles.addBtn} onPress={addContact}>
          <Text style={styles.addBtnText}>+ ADD CONTACT</Text>
        </TouchableOpacity>

        {/* API Endpoint */}
        <Text style={styles.sectionLabel}>BACKEND API URL</Text>
        <TextInput
          style={styles.input}
          placeholder="http://localhost:8000"
          placeholderTextColor={Colors.textMuted}
          value={apiUrl}
          onChangeText={setApiUrl}
          autoCapitalize="none"
          autoCorrect={false}
        />

        {/* Zero Retention */}
        <Text style={styles.sectionLabel}>DATA RETENTION</Text>
        <TouchableOpacity
          style={styles.toggleRow}
          onPress={() => setZeroRetention(!zeroRetention)}
        >
          <View style={[styles.toggle, zeroRetention && styles.toggleActive]}>
            <View style={[styles.toggleKnob, zeroRetention && styles.toggleKnobActive]} />
          </View>
          <View>
            <Text style={styles.toggleLabel}>Zero-Retention Mode</Text>
            <Text style={styles.toggleSubtext}>
              Wipe image buffers after extracting coordinates
            </Text>
          </View>
        </TouchableOpacity>

        <TouchableOpacity style={styles.saveBtn} onPress={saveSettings}>
          <Text style={styles.saveBtnText}>SAVE SETTINGS</Text>
        </TouchableOpacity>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.bgDarkest,
  },
  scroll: {
    padding: Spacing.lg,
    paddingBottom: Spacing.xxl,
  },
  title: {
    fontSize: 20,
    fontWeight: 'bold',
    color: Colors.textPrimary,
    letterSpacing: 1,
    paddingVertical: Spacing.lg,
  },
  sectionLabel: {
    ...Typography.mono,
    fontSize: 11,
    marginTop: Spacing.xl,
    marginBottom: Spacing.sm,
  },
  contactRow: {
    backgroundColor: Colors.bgCard,
    borderRadius: BorderRadius.md,
    borderWidth: 1,
    borderColor: Colors.borderDim,
    padding: Spacing.md,
    marginBottom: Spacing.sm,
  },
  input: {
    backgroundColor: Colors.bgInput,
    borderRadius: BorderRadius.md,
    borderWidth: 1,
    borderColor: Colors.border,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.sm,
    color: Colors.textPrimary,
    fontSize: 14,
    marginBottom: Spacing.sm,
  },
  removeText: {
    ...Typography.mono,
    fontSize: 11,
    color: Colors.emergency,
    textAlign: 'right',
  },
  addBtn: {
    paddingVertical: Spacing.sm,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: Colors.cyan,
    borderStyle: 'dashed',
    borderRadius: BorderRadius.md,
    marginTop: Spacing.xs,
  },
  addBtnText: {
    ...Typography.mono,
    color: Colors.cyan,
  },
  toggleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.md,
    paddingVertical: Spacing.sm,
  },
  toggle: {
    width: 44,
    height: 24,
    borderRadius: 12,
    backgroundColor: Colors.bgInput,
    borderWidth: 1,
    borderColor: Colors.border,
    justifyContent: 'center',
    paddingHorizontal: 2,
  },
  toggleActive: {
    backgroundColor: Colors.cyan + '30',
    borderColor: Colors.cyan,
  },
  toggleKnob: {
    width: 18,
    height: 18,
    borderRadius: 9,
    backgroundColor: Colors.textMuted,
  },
  toggleKnobActive: {
    backgroundColor: Colors.cyan,
    alignSelf: 'flex-end',
  },
  toggleLabel: {
    ...Typography.subtitle,
  fontSize: 14,
  },
  toggleSubtext: {
    ...Typography.caption,
    marginTop: 2,
  },
  saveBtn: {
    marginTop: Spacing.xxl,
    paddingVertical: Spacing.lg,
    borderRadius: BorderRadius.lg,
    backgroundColor: Colors.cyan + '20',
    borderWidth: 2,
    borderColor: Colors.cyan,
    alignItems: 'center',
  },
  saveBtnText: {
    fontSize: 16,
    fontWeight: 'bold',
    color: Colors.cyan,
    letterSpacing: 2,
  },
});
