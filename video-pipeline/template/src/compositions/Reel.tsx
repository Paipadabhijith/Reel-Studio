import React from 'react';
import type {VideoProps} from '../types';
import {Body} from './Body';

// 1080x1920 · 30 fps · captions burned in
export const Reel: React.FC<VideoProps> = (props) => <Body {...props} kind="reel" captions={props.captions ?? true} />;
