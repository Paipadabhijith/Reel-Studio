import React from 'react';
import type {VideoProps} from '../types';
import {Body} from './Body';

// 1920x1080 · 30 fps · no burned captions (a sidecar .srt is written instead)
export const LongForm: React.FC<VideoProps> = (props) => <Body {...props} kind="long" captions={props.captions ?? false} />;
