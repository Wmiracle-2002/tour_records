package com.miracle.footmarks

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.only
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.WindowInsetsSides
import androidx.compose.material3.Scaffold
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.Modifier
import androidx.navigation.compose.rememberNavController
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.compose.runtime.getValue
import com.miracle.footmarks.data.remote.CloudSession
import com.miracle.footmarks.data.local.util.PhotoManager
import javax.inject.Inject
import com.miracle.footmarks.ui.navigation.MainBottomBar
import com.miracle.footmarks.ui.navigation.MainNavHost
import com.miracle.footmarks.ui.navigation.bottomNavItems
import com.miracle.footmarks.ui.theme.FootmarksTheme
import dagger.hilt.android.AndroidEntryPoint

@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    @Inject lateinit var cloudSession: CloudSession
    @Inject lateinit var photoManager: PhotoManager
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        photoManager.clearLegacyLocalPhotosOnce()
        enableEdgeToEdge()
        setContent {
            FootmarksTheme {
                val navController = rememberNavController()
                val backStackEntry by navController.currentBackStackEntryAsState()
                val showBottomBar = bottomNavItems.any { it.route == backStackEntry?.destination?.route }
                val isAdmin = cloudSession.accountRole == "admin"
                val isImeVisible = WindowInsets.ime.getBottom(LocalDensity.current) > 0
                Scaffold(
                    modifier = Modifier.fillMaxSize(),
                    contentWindowInsets = if (isImeVisible) {
                        WindowInsets.safeDrawing.only(
                            WindowInsetsSides.Horizontal + WindowInsetsSides.Top
                        )
                    } else {
                        WindowInsets.safeDrawing
                    },
                    bottomBar = {
                        if (!isImeVisible && showBottomBar) {
                            MainBottomBar(navController, cloudSession)
                        }
                    }
                ) { innerPadding ->
                    MainNavHost(
                        navController = navController,
                        isAdmin = isAdmin,
                        session = cloudSession,
                        modifier = Modifier.padding(innerPadding)
                    )
                }
            }
        }
    }
}
