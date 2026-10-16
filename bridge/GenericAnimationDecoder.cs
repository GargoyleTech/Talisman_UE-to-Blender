using CUE4Parse.UE4.Assets.Exports.Animation;
using CUE4Parse.UE4.Objects.Core.Math;
using CUE4Parse_Conversion.Animations;
using CUE4Parse_Conversion.Animations.PSA;

/// <summary>Stock clips, including additive clips baked onto their authored base.</summary>
internal static class GenericAnimationDecoder
{
    public static CAnimSequence Decode(UAnimSequence source, USkeleton skeleton) => Decode(source, skeleton, new HashSet<string>());

    private static CAnimSequence Decode(UAnimSequence source, USkeleton skeleton, HashSet<string> visiting)
    {
        if (!visiting.Add(source.GetPathName())) throw new InvalidOperationException("Cyclic additive animation reference.");
        try
        {
            if (source.AdditiveAnimType == EAdditiveAnimationType.AAT_None)
                return source.ConvertAnims().Sequences.First();
            if (!source.IsValidAdditive()) throw new InvalidOperationException("Additive clip has no valid reference pose.");
            var baseType = source.RefPoseType;
            var baseFrame = source.RefFrameIndex;
            if (baseType == EAdditiveBasePoseType.ABPT_LocalAnimFrame)
                throw new NotSupportedException("LocalAnimFrame additive bases are not supported by the generic importer yet.");

            // CUE4Parse 1.2.2 indexes a one-element sampled reference-pose array
            // by RefFrameIndex (e.g. 676), and cycles scaled bases instead of
            // time-scaling them. Decode against bind pose at index zero, then
            // rebase the resulting additive deltas onto the real reference.
            CAnimSequence decoded;
            try
            {
                source.RefPoseType = EAdditiveBasePoseType.ABPT_RefPose;
                source.RefFrameIndex = 0;
                decoded = source.ConvertAnims().Sequences.First();
            }
            finally { source.RefPoseType = baseType; source.RefFrameIndex = baseFrame; }
            RepairImplicitAdditiveScales(source, decoded, skeleton);
            if (baseType == EAdditiveBasePoseType.ABPT_RefPose) return decoded;
            var reference = source.RefPoseSeq?.Load<UAnimSequence>()
                ?? throw new InvalidOperationException("Additive reference animation is unavailable.");
            var referenceSkeleton = reference.Skeleton?.Load<USkeleton>()
                ?? throw new InvalidOperationException("Additive reference Skeleton is unavailable.");
            if (!skeleton.ReferenceSkeleton.FinalRefBoneInfo.Select(bone => bone.Name.Text).SequenceEqual(
                    referenceSkeleton.ReferenceSkeleton.FinalRefBoneInfo.Select(bone => bone.Name.Text)))
                throw new NotSupportedException("Additive bases on a different bone hierarchy require retargeting.");
            var referenceClip = Decode(reference, referenceSkeleton, visiting);
            return Rebase(decoded, referenceClip, skeleton, baseType, baseFrame,
                source.AdditiveAnimType == EAdditiveAnimationType.AAT_RotationOffsetMeshSpace);
        }
        finally { visiting.Remove(source.GetPathName()); }
    }

    private static void RepairImplicitAdditiveScales(UAnimSequence source, CAnimSequence decoded, USkeleton skeleton)
    {
        if (source.CompressedDataStructure is not FUECompressedAnimData data ||
            data.KeyEncodingFormat != AnimationKeyFormat.AKF_PerTrackCompression) return;
        for (var bone = 0; bone < decoded.Tracks.Count; bone++)
        {
            var track = source.FindTrackForBoneIndex(bone);
            if (track < 0) continue;
            var offset = data.CompressedScaleOffsets.IsValid() ? data.CompressedScaleOffsets.OffsetData[track] : -1;
            if (offset >= 0) continue;
            // An omitted additive scale is ZERO delta. CUE4Parse's legacy
            // per-track reader supplies ONE and the additive bake doubles it,
            // exponentially inflating long bone chains. Restore the bind scale.
            decoded.Tracks[bone].KeyScale = [skeleton.ReferenceSkeleton.FinalRefBonePose[bone].Scale3D];
        }
    }

    private static FTransform[] Sample(CAnimSequence clip, USkeleton skeleton, float frame)
    {
        var bind = skeleton.ReferenceSkeleton.FinalRefBonePose;
        return Enumerable.Range(0, bind.Length).Select(index =>
        {
            var rotation = bind[index].Rotation;
            var translation = bind[index].Translation;
            var scale = bind[index].Scale3D;
            if (index < clip.Tracks.Count)
                clip.Tracks[index].GetBoneTransform(frame, clip.NumFrames, ref rotation, ref translation, ref scale);
            return new FTransform(rotation, translation, scale);
        }).ToArray();
    }

    private static FQuat[] MeshRotations(FTransform[] pose, int[] parents)
    {
        var rotations = new FQuat[pose.Length];
        for (var index = 0; index < pose.Length; index++)
        {
            var parent = parents[index];
            rotations[index] = parent < 0 ? pose[index].Rotation : rotations[parent] * pose[index].Rotation;
        }
        return rotations;
    }

    internal static FTransform[] RebasePose(FTransform[] bind, FTransform[] posed, FTransform[] basePose, int[] parents, bool meshSpace)
    {
        var bindRotations = meshSpace ? MeshRotations(bind, parents) : bind.Select(bone => bone.Rotation).ToArray();
        var posedRotations = meshSpace ? MeshRotations(posed, parents) : posed.Select(bone => bone.Rotation).ToArray();
        var baseRotations = meshSpace ? MeshRotations(basePose, parents) : basePose.Select(bone => bone.Rotation).ToArray();
        var finalRotations = new FQuat[bind.Length];
        var result = new FTransform[bind.Length];
        for (var bone = 0; bone < bind.Length; bone++)
        {
            var bindScale = bind[bone].Scale3D;
            if (MathF.Abs(bindScale.X * bindScale.Y * bindScale.Z) < 1e-12f)
                throw new NotSupportedException("Cannot rebase an additive clip with zero reference scale.");
            finalRotations[bone] = posedRotations[bone] * bindRotations[bone].Inverse() * baseRotations[bone];
            var localRotation = meshSpace && parents[bone] >= 0
                ? finalRotations[parents[bone]].Inverse() * finalRotations[bone] : finalRotations[bone];
            localRotation.Normalize();
            result[bone] = new FTransform(localRotation,
                basePose[bone].Translation + posed[bone].Translation - bind[bone].Translation,
                basePose[bone].Scale3D * (posed[bone].Scale3D / bindScale));
        }
        return result;
    }

    internal static CAnimSequence Rebase(CAnimSequence clip, CAnimSequence reference, USkeleton skeleton,
        EAdditiveBasePoseType baseType, int baseFrame, bool meshSpace)
    {
        var bind = skeleton.ReferenceSkeleton.FinalRefBonePose;
        var result = Enumerable.Range(0, bind.Length).Select(_ => new CAnimTrack(clip.NumFrames)).ToList();
        var parents = skeleton.ReferenceSkeleton.FinalRefBoneInfo.Select(bone => bone.ParentIndex).ToArray();
        for (var frame = 0; frame < clip.NumFrames; frame++)
        {
            var referenceFrame = baseType == EAdditiveBasePoseType.ABPT_AnimScaled
                ? frame * (reference.NumFrames - 1.0f) / Math.Max(1, clip.NumFrames - 1)
                : Math.Clamp(baseFrame, 0, Math.Max(0, reference.NumFrames - 1));
            var posed = Sample(clip, skeleton, frame);
            var basePose = Sample(reference, skeleton, referenceFrame);
            var finalPose = RebasePose(bind, posed, basePose, parents, meshSpace);
            for (var bone = 0; bone < bind.Length; bone++)
            {
                result[bone].KeyQuat[frame] = finalPose[bone].Rotation;
                result[bone].KeyPos[frame] = finalPose[bone].Translation;
                result[bone].KeyScale[frame] = finalPose[bone].Scale3D;
            }
        }
        clip.Tracks = result;
        return clip;
    }
}
