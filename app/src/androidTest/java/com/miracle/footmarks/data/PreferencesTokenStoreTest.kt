package com.miracle.footmarks.data

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.miracle.footmarks.data.remote.PreferencesTokenStore
import com.miracle.footmarks.data.remote.Tokens
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PreferencesTokenStoreTest {
    @Test
    fun persistedTokensAreEncryptedAndCanBeReloaded() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val preferences = context.getSharedPreferences("cloud_session", android.content.Context.MODE_PRIVATE)
        preferences.edit().clear().commit()
        val store = PreferencesTokenStore(context)
        store.tokens = Tokens("private-access-value", "private-refresh-value", 42, "user")

        val stored = preferences.getString("session_blob", null).orEmpty()
        assertFalse(stored.contains("private-access-value"))
        assertFalse(stored.contains("private-refresh-value"))
        assertEquals(42L, PreferencesTokenStore(context).tokens?.userId)
        assertEquals("private-refresh-value", PreferencesTokenStore(context).tokens?.refreshToken)

        store.tokens = null
        assertNull(PreferencesTokenStore(context).tokens)
    }

    @Test
    fun sessionOnlyTokensDoNotPersist() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val preferences = context.getSharedPreferences("cloud_session", android.content.Context.MODE_PRIVATE)
        preferences.edit().clear().commit()
        val store = PreferencesTokenStore(context)
        store.keepSignedIn = false
        store.tokens = Tokens("temporary", "secret", 12, "user")
        assertEquals("temporary", store.tokens?.accessToken)
        assertNull(PreferencesTokenStore(context).tokens)
    }
}
