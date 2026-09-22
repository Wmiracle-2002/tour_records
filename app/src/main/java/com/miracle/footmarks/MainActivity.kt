package com.miracle.footmarks

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Scaffold
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.Modifier
import androidx.navigation.compose.rememberNavController
import com.miracle.footmarks.ui.navigation.MainBottomBar
import com.miracle.footmarks.ui.navigation.MainNavHost
import com.miracle.footmarks.ui.theme.FootmarksTheme
import dagger.hilt.android.AndroidEntryPoint

@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            FootmarksTheme {
                val navController = rememberNavController()
                val isImeVisible = WindowInsets.ime.getBottom(LocalDensity.current) > 0
                Scaffold(
                    modifier = Modifier.fillMaxSize(),
                    bottomBar = {
                        if (!isImeVisible) {
                            MainBottomBar(navController)
                        }
                    }
                ) { innerPadding ->
                    MainNavHost(
                        navController = navController,
                        modifier = Modifier.padding(innerPadding)
                    )
                }
            }
        }
    }
}
