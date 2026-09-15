package com.miracle.footmarks

import android.content.pm.PackageManager
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ManifestPermissionsTest {

    @Test
    fun localDemoRequestsNoSystemPermissions() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val packageInfo = context.packageManager.getPackageInfo(
            context.packageName,
            PackageManager.GET_PERMISSIONS
        )

        assertTrue(
            packageInfo.requestedPermissions.orEmpty().all {
                it.startsWith("${context.packageName}.")
            }
        )
    }
}
